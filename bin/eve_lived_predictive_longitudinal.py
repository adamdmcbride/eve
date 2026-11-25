#!/usr/bin/env python3
"""Preregister and score repeated lived predictive-perception windows.

The first lived PP-1 canary was one short observation window.  This evaluator
turns repetition into a fail-closed protocol: the window count, effect size,
sign test, and temporal-specificity negative control are fixed before new
samples are collected.  It emits aggregate evidence only and can never return
a subjective-consciousness verdict.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_lived_feature_stream as lived  # noqa: E402


TRANSFER_PATH = ROOT / "bin" / "eve_lived_predictive_transfer.py"
REGISTRATION_SCHEMA = "eve.lived_predictive_longitudinal_registration.v1"
REPORT_SCHEMA = "eve.lived_predictive_longitudinal_report.v1"
BOUNDARY = (
    "Repeated read-only aggregate forecast evidence for PP-1; not subjective "
    "experience and not proof of consciousness."
)


def _load_transfer_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("eve_lived_predictive_transfer", TRANSFER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("lived predictive transfer evaluator is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _timestamp(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("an ISO-8601 timestamp is required")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _parsed(value: object) -> datetime:
    return datetime.fromisoformat(_timestamp(value))


def _finite(value: object, *, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _registration_material(payload: Mapping[str, object]) -> Dict[str, object]:
    try:
        planned = int(payload.get("planned_window_count") or 0)
        minimum = int(payload.get("minimum_valid_windows") or 0)
        gap = float(payload.get("window_gap_seconds") or 0.0)
    except (TypeError, ValueError) as exc:
        raise ValueError("window count and gap contract is invalid") from exc
    minimum_effect = _finite(
        payload.get("minimum_median_effect_pp"), name="minimum_median_effect_pp"
    )
    positive_fraction = _finite(
        payload.get("minimum_positive_window_fraction"),
        name="minimum_positive_window_fraction",
    )
    maximum_p = _finite(payload.get("maximum_sign_test_p"), name="maximum_sign_test_p")
    temporal_specificity = _finite(
        payload.get("minimum_temporal_specificity_pp"),
        name="minimum_temporal_specificity_pp",
    )
    if planned < 6 or minimum < 6 or minimum > planned:
        raise ValueError("at least six planned and valid windows are required")
    if gap < 0:
        raise ValueError("window_gap_seconds must be non-negative")
    if minimum_effect <= 0 or temporal_specificity <= 0:
        raise ValueError("effect and temporal-specificity thresholds must be positive")
    if not 0.5 < positive_fraction <= 1.0:
        raise ValueError("minimum_positive_window_fraction must be in (0.5, 1]")
    if not 0 < maximum_p <= 0.05:
        raise ValueError("maximum_sign_test_p must be in (0, 0.05]")
    material = {
        "schema_version": REGISTRATION_SCHEMA,
        "protocol_id": str(payload.get("protocol_id") or "").strip()[:120],
        "registered_at": _timestamp(payload.get("registered_at")),
        "subject_system_id": str(payload.get("subject_system_id") or "").strip()[:120],
        "evaluator_id": str(payload.get("evaluator_id") or "").strip()[:120],
        "contract_digest": str(payload.get("contract_digest") or "").strip(),
        "planned_window_count": planned,
        "minimum_valid_windows": minimum,
        "window_gap_seconds": gap,
        "primary_metric": "median_window_paired_accuracy_delta_pp",
        "minimum_median_effect_pp": minimum_effect,
        "minimum_positive_window_fraction": positive_fraction,
        "maximum_sign_test_p": maximum_p,
        "negative_control": "one_step_future_actual_alignment",
        "minimum_temporal_specificity_pp": temporal_specificity,
        "indicator_id": "PP-1",
        "evidence_class": "lived",
    }
    if not material["protocol_id"] or not material["subject_system_id"] or not material["evaluator_id"]:
        raise ValueError("protocol_id, subject_system_id, and evaluator_id are required")
    if str(material["subject_system_id"]).lower() == str(material["evaluator_id"]).lower():
        raise ValueError("the evaluator must be distinct from Eve")
    digest = str(material["contract_digest"])
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest.lower()):
        raise ValueError("contract_digest must be a SHA-256 hex digest")
    return material


def preregister(payload: Mapping[str, object]) -> Dict[str, object]:
    material = _registration_material(payload)
    return {
        **material,
        "status": "preregistered",
        "registration_digest": _digest(material),
        "consciousness_verdict_authorized": False,
        "boundary": BOUNDARY,
    }


def validate_registration(payload: Mapping[str, object]) -> Dict[str, object]:
    if payload.get("schema_version") != REGISTRATION_SCHEMA:
        raise ValueError("longitudinal registration schema mismatch")
    material = _registration_material(payload)
    if str(payload.get("registration_digest") or "") != _digest(material):
        raise ValueError("registration digest mismatch; protocol may have changed")
    return material


def _report_window(
    report: Mapping[str, object],
    registration: Mapping[str, object],
) -> Dict[str, object]:
    if report.get("schema_version") != "eve.lived_predictive_transfer_evaluation.v1":
        raise ValueError("window report schema mismatch")
    if report.get("status") != "evidence_ready":
        raise ValueError("window is not evidence-ready")
    if str(report.get("contract_digest") or "") != registration["contract_digest"]:
        raise ValueError("window contract digest mismatch")
    checks = report.get("checks") if isinstance(report.get("checks"), Mapping) else {}
    if not checks or not all(value is True for value in checks.values()):
        raise ValueError("window checks are incomplete")
    if report.get("runtime_mutated") is not False or report.get("consciousness_proven") is not False:
        raise ValueError("window crossed the read-only or consciousness boundary")
    samples = report.get("samples") if isinstance(report.get("samples"), list) else []
    if not samples:
        raise ValueError("window has no samples")
    sample_times = [_parsed(sample.get("observed_at")) for sample in samples if isinstance(sample, Mapping)]
    if len(sample_times) != len(samples) or any(
        later <= earlier for earlier, later in zip(sample_times, sample_times[1:])
    ):
        raise ValueError("window sample order is invalid")
    if sample_times[0] <= _parsed(registration["registered_at"]):
        raise ValueError("window evidence predates preregistration")
    for sample in samples:
        if not isinstance(sample, Mapping):
            raise ValueError("window sample is malformed")
        if sample.get("read_only") is not True or any(
            bool(sample.get(key))
            for key in (
                "raw_media_retained",
                "user_content_retained",
                "process_identity_retained",
                "action_authority",
            )
        ):
            raise ValueError("window violates the privacy/read-only contract")

    arms = report.get("arms") if isinstance(report.get("arms"), Mapping) else {}
    intact = arms.get("intact") if isinstance(arms.get("intact"), list) else []
    lesion = arms.get("lesion") if isinstance(arms.get("lesion"), list) else []

    def keyed(records: Sequence[object]) -> Dict[Tuple[str, int], Mapping[str, object]]:
        output: Dict[Tuple[str, int], Mapping[str, object]] = {}
        for record in records:
            if not isinstance(record, Mapping) or record.get("action_authority") is not False:
                raise ValueError("forecast record is malformed or has action authority")
            key = (str(record.get("feature_id") or ""), int(record.get("sample_index")))
            if not key[0] or key in output:
                raise ValueError("forecast pair identity is missing or duplicated")
            output[key] = record
        return output

    intact_by_key = keyed(intact)
    lesion_by_key = keyed(lesion)
    if not intact_by_key or set(intact_by_key) != set(lesion_by_key):
        raise ValueError("intact and lesion forecasts are not paired")
    paired_deltas: List[float] = []
    for key in sorted(intact_by_key):
        left = intact_by_key[key]
        right = lesion_by_key[key]
        if _finite(left.get("actual"), name="intact actual") != _finite(
            right.get("actual"), name="lesion actual"
        ):
            raise ValueError("paired forecasts disagree about the observation")
        paired_deltas.append(
            _finite(left.get("accuracy_percent"), name="intact accuracy")
            - _finite(right.get("accuracy_percent"), name="lesion accuracy")
        )

    feature_limits: Dict[str, float] = {}
    for sample in samples:
        features = sample.get("features") if isinstance(sample.get("features"), Mapping) else {}
        for feature_id, record in features.items():
            if isinstance(record, Mapping):
                limit = _finite(record.get("limit"), name="feature limit")
                if limit <= 0:
                    raise ValueError("feature limit must be positive")
                feature_limits[str(feature_id)] = limit

    aligned: List[float] = []
    shifted: List[float] = []
    grouped: Dict[str, List[Mapping[str, object]]] = {}
    for (feature_id, _), record in intact_by_key.items():
        grouped.setdefault(feature_id, []).append(record)
    for feature_id, records in grouped.items():
        ordered = sorted(records, key=lambda item: int(item.get("sample_index")))
        limit = feature_limits.get(feature_id)
        if limit is None:
            raise ValueError("forecast feature is absent from sample contract")
        for current, future in zip(ordered, ordered[1:]):
            prediction = _finite(current.get("prediction"), name="prediction")
            future_actual = _finite(future.get("actual"), name="future actual")
            aligned.append(_finite(current.get("accuracy_percent"), name="aligned accuracy"))
            shifted_error = abs(prediction - future_actual) * 100.0 / limit
            shifted.append(max(0.0, 100.0 - shifted_error))
    if not aligned or len(aligned) != len(shifted):
        raise ValueError("window lacks temporal-specificity comparisons")
    return {
        "source_report_digest": _digest(report),
        "started_at": sample_times[0].isoformat(),
        "ended_at": sample_times[-1].isoformat(),
        "paired_comparison_count": len(paired_deltas),
        "paired_effect_pp": statistics.fmean(paired_deltas),
        "temporal_specificity_comparison_count": len(aligned),
        "temporal_specificity_pp": statistics.fmean(aligned) - statistics.fmean(shifted),
        "observed_feature_ids": sorted(grouped),
    }


def exact_two_sided_sign_p(effects: Sequence[float]) -> float | None:
    nonzero = [value for value in effects if abs(value) > 1e-12]
    if not nonzero:
        return None
    positive = sum(value > 0 for value in nonzero)
    tail = min(positive, len(nonzero) - positive)
    probability = sum(math.comb(len(nonzero), k) for k in range(tail + 1)) / (2 ** len(nonzero))
    return min(1.0, 2.0 * probability)


def score_reports(
    registration: Mapping[str, object],
    reports: Iterable[Mapping[str, object]],
    *,
    scored_at: object,
    scored_by: str,
) -> Dict[str, object]:
    registered = validate_registration(registration)
    scorer = str(scored_by or "").strip()[:120]
    if not scorer or scorer.lower() == str(registered["subject_system_id"]).lower():
        raise ValueError("scoring requires an evaluator distinct from Eve")
    scored_timestamp = _timestamp(scored_at)
    if _parsed(scored_timestamp) <= _parsed(registered["registered_at"]):
        raise ValueError("scoring must occur after preregistration")
    windows = [_report_window(report, registered) for report in reports]
    if len({item["source_report_digest"] for item in windows}) != len(windows):
        raise ValueError("duplicate window reports are not independent evidence")
    ordered = sorted(windows, key=lambda item: item["started_at"])
    for previous, current in zip(ordered, ordered[1:]):
        if _parsed(current["started_at"]) <= _parsed(previous["ended_at"]):
            raise ValueError("longitudinal windows overlap")
    effects = [float(item["paired_effect_pp"]) for item in ordered]
    temporal = [float(item["temporal_specificity_pp"]) for item in ordered]
    sign_p = exact_two_sided_sign_p(effects)
    positive_fraction = sum(value > 0 for value in effects) / len(effects) if effects else 0.0
    median_effect = statistics.median(effects) if effects else None
    median_temporal = statistics.median(temporal) if temporal else None
    enough = len(ordered) >= int(registered["minimum_valid_windows"])
    gates = {
        "minimum_valid_windows_met": enough,
        "median_effect_met": bool(
            median_effect is not None
            and median_effect >= float(registered["minimum_median_effect_pp"])
        ),
        "positive_window_fraction_met": (
            positive_fraction >= float(registered["minimum_positive_window_fraction"])
        ),
        "exact_sign_test_met": bool(
            sign_p is not None and sign_p <= float(registered["maximum_sign_test_p"])
        ),
        "temporal_specificity_negative_control_met": bool(
            median_temporal is not None
            and median_temporal >= float(registered["minimum_temporal_specificity_pp"])
        ),
    }
    # These windows are non-overlapping but normally collected in one
    # contiguous host session.  That is repeatability evidence, not independent
    # replication: load, memory, and scheduler dynamics are autocorrelated.
    # Keep the exact sign calculation visible as a descriptive pattern and do
    # not promote its nominal p-value to an independence claim.
    inter_window_gaps_seconds = [
        (_parsed(current["started_at"]) - _parsed(previous["ended_at"])).total_seconds()
        for previous, current in zip(ordered, ordered[1:])
    ]
    if all(gates.values()):
        status = "short_horizon_supported"
        reason = "all preregistered short-horizon PP-1 gates passed"
    elif enough and (
        (median_effect is not None and median_effect <= -float(registered["minimum_median_effect_pp"]))
        or (
            median_temporal is not None
            and median_temporal <= -float(registered["minimum_temporal_specificity_pp"])
        )
    ):
        status = "challenged"
        reason = "a preregistered directional prediction reversed"
    else:
        status = "inconclusive"
        reason = "one or more preregistered longitudinal gates did not pass"
    return {
        "schema_version": REPORT_SCHEMA,
        "protocol_id": registered["protocol_id"],
        "registration_digest": registration["registration_digest"],
        "scored_at": scored_timestamp,
        "scored_by": scorer,
        "status": status,
        "reason": reason,
        "indicator_id": "PP-1",
        "evidence_class": "lived",
        "valid_window_count": len(ordered),
        "planned_window_count": registered["planned_window_count"],
        "median_window_effect_pp": round(median_effect, 6) if median_effect is not None else None,
        "positive_window_fraction": round(positive_fraction, 6),
        "exact_two_sided_sign_test_p": round(sign_p, 8) if sign_p is not None else None,
        "exact_sign_test_interpretation": "descriptive_only_due_serial_dependence",
        "inter_window_gaps_seconds": [round(value, 6) for value in inter_window_gaps_seconds],
        "serial_independence_established": False,
        "independent_replication_established": False,
        "median_temporal_specificity_pp": (
            round(median_temporal, 6) if median_temporal is not None else None
        ),
        "gates": gates,
        "windows": [
            {
                **item,
                "paired_effect_pp": round(float(item["paired_effect_pp"]), 6),
                "temporal_specificity_pp": round(
                    float(item["temporal_specificity_pp"]), 6
                ),
            }
            for item in ordered
        ],
        "runtime_mutated": False,
        "action_authority": False,
        "consciousness_proven": False,
        "subjective_experience_inferred": False,
        "boundary": BOUNDARY,
    }


def collect_windows(
    registration: Mapping[str, object],
    contract: Mapping[str, object],
    *,
    output_dir: Path,
) -> List[Dict[str, object]]:
    registered = validate_registration(registration)
    validated_contract = lived.validate_contract(contract)
    if validated_contract["contract_digest"] != registered["contract_digest"]:
        raise ValueError("registration and lived feature contract do not match")
    transfer = _load_transfer_module()
    output_dir.mkdir(parents=True, exist_ok=True)
    reports: List[Dict[str, object]] = []
    for index in range(int(registered["planned_window_count"])):
        report = transfer.evaluate_samples(
            validated_contract,
            transfer.collect_samples(validated_contract),
            protocol_trial_id=f"{registered['protocol_id']}-window-{index + 1}",
        )
        path = output_dir / f"window-{index + 1:02d}.json"
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        reports.append(report)
        if index + 1 < int(registered["planned_window_count"]):
            time.sleep(float(registered["window_gap_seconds"]))
    return reports


def _read_json(path: Path) -> Mapping[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    register = sub.add_parser("register")
    register.add_argument("--contract", type=Path, required=True)
    register.add_argument("--output", type=Path, required=True)
    register.add_argument("--protocol-id", required=True)
    register.add_argument("--evaluator-id", required=True)
    register.add_argument("--windows", type=int, default=6)
    register.add_argument("--minimum-valid-windows", type=int, default=6)
    register.add_argument("--window-gap-seconds", type=float, default=3.0)
    register.add_argument("--minimum-median-effect-pp", type=float, default=0.25)
    register.add_argument("--minimum-positive-window-fraction", type=float, default=1.0)
    register.add_argument("--maximum-sign-test-p", type=float, default=0.05)
    register.add_argument("--minimum-temporal-specificity-pp", type=float, default=0.1)

    collect = sub.add_parser("collect")
    collect.add_argument("--registration", type=Path, required=True)
    collect.add_argument("--contract", type=Path, required=True)
    collect.add_argument("--window-dir", type=Path, required=True)
    collect.add_argument("--output", type=Path, required=True)
    collect.add_argument("--scored-by", required=True)

    score = sub.add_parser("score")
    score.add_argument("--registration", type=Path, required=True)
    score.add_argument("--report", type=Path, action="append", required=True)
    score.add_argument("--output", type=Path, required=True)
    score.add_argument("--scored-by", required=True)
    args = parser.parse_args()

    if args.command == "register":
        contract = lived.validate_contract(_read_json(args.contract))
        result = preregister(
            {
                "protocol_id": args.protocol_id,
                "registered_at": datetime.now(timezone.utc).isoformat(),
                "subject_system_id": "Eve",
                "evaluator_id": args.evaluator_id,
                "contract_digest": contract["contract_digest"],
                "planned_window_count": args.windows,
                "minimum_valid_windows": args.minimum_valid_windows,
                "window_gap_seconds": args.window_gap_seconds,
                "minimum_median_effect_pp": args.minimum_median_effect_pp,
                "minimum_positive_window_fraction": args.minimum_positive_window_fraction,
                "maximum_sign_test_p": args.maximum_sign_test_p,
                "minimum_temporal_specificity_pp": args.minimum_temporal_specificity_pp,
            }
        )
    else:
        registration = _read_json(args.registration)
        if args.command == "collect":
            reports = collect_windows(
                registration,
                _read_json(args.contract),
                output_dir=args.window_dir,
            )
        else:
            reports = [_read_json(path) for path in args.report]
        result = score_reports(
            registration,
            reports,
            scored_at=datetime.now(timezone.utc).isoformat(),
            scored_by=args.scored_by,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0 if result.get("status") in {
        "preregistered",
        "short_horizon_supported",
        "inconclusive",
    } else 1


if __name__ == "__main__":
    raise SystemExit(main())
