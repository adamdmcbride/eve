#!/usr/bin/env python3
"""Hash-frozen matched evaluator for Eve's observable social prediction loop.

The private specification may contain synthetic conversational fixtures.  The
output retains only aggregate scores and case fingerprints.  This evaluator is
a post-implementation regression/intervention test unless an external owner
freezes its registration before a future implementation change.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Dict, List, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_social_prediction as social  # noqa: E402


SPEC_SCHEMA = "eve.observable_social_prediction_private_eval.v1"
REGISTRATION_SCHEMA = "eve.observable_social_prediction_registration.v1"
RESULT_SCHEMA = "eve.observable_social_prediction_eval_result.v1"
BOUNDARY = (
    "A pass is functional evidence for exact-lineage observable-response "
    "prediction and feedback, not evidence of private mental-state access, "
    "subjective experience, or consciousness."
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _timestamp(value: object, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} timestamp must be timezone-aware")
    parsed = parsed.astimezone(timezone.utc)
    if parsed > datetime.now(timezone.utc) + timedelta(seconds=5):
        raise ValueError(f"{label} timestamp is in the future")
    return parsed


def _validate_registration(
    registration: Mapping[str, object],
    *,
    spec_path: Path,
    evaluator_path: Path,
    module_path: Path,
    integration_path: Path,
    kernel_path: Path,
) -> Dict[str, str]:
    if registration.get("schema_version") != REGISTRATION_SCHEMA:
        raise ValueError("registration schema mismatch")
    _timestamp(registration.get("registered_at"), "registration")
    expected = registration.get("sha256")
    if not isinstance(expected, Mapping):
        raise ValueError("registration must bind sha256 values")
    observed = {
        "spec": _sha256(spec_path),
        "evaluator": _sha256(evaluator_path),
        "module": _sha256(module_path),
        "integration": _sha256(integration_path),
        "kernel": _sha256(kernel_path),
    }
    for key, digest in observed.items():
        if expected.get(key) != digest:
            raise ValueError(f"registration hash mismatch for {key}")
    return observed


def run(spec: Mapping[str, object]) -> Dict[str, object]:
    if spec.get("schema_version") != SPEC_SCHEMA:
        raise ValueError("private spec schema mismatch")
    _timestamp(spec.get("frozen_at"), "private spec")
    cases = spec.get("cases")
    if not isinstance(cases, list) or len(cases) < 6:
        raise ValueError("at least six matched cases are required")
    threshold = float(spec.get("minimum_mean_brier_improvement") or 0.05)
    if not (0.0 < threshold <= 0.5):
        raise ValueError("minimum_mean_brier_improvement must be in (0, 0.5]")

    intact_losses: List[float] = []
    lesioned_losses: List[float] = []
    aggregate_cases: List[Dict[str, object]] = []
    feedback_records: List[Dict[str, object]] = []
    for index, raw in enumerate(cases):
        if not isinstance(raw, Mapping):
            raise ValueError("each case must be an object")
        expected_class = str(raw.get("expected_observed_class") or "")
        if expected_class not in social.RESPONSE_CLASSES:
            raise ValueError("case expected_observed_class is invalid")
        made_at = str(raw.get("made_at") or "2026-08-23T20:00:00+00:00")
        observed_at = str(raw.get("observed_at") or "2026-08-23T20:00:01+00:00")
        prediction = social.build_prediction(
            reply_text=raw.get("reply_text"),
            inbound_text=raw.get("inbound_text"),
            thread_id=f"private-thread-{index}",
            source_message_id=f"private-source-{index}",
            reply_message_id=f"private-reply-{index}",
            made_at=made_at,
        )
        observed_class = social.classify_observed_response(
            raw.get("observed_text"),
            prediction=prediction,
            correction=bool(raw.get("explicit_correction")),
            explicit_acceptance=bool(raw.get("explicit_acceptance")),
        )
        intact = social.score_prediction(
            prediction,
            observed_class,
            observed_message_id=f"private-observed-{index}",
            observed_at=observed_at,
        )
        lesion = social.score_prediction(
            prediction,
            observed_class,
            observed_message_id=f"private-observed-{index}",
            observed_at=observed_at,
            lesioned=True,
        )
        lineage_ok = social.observation_matches_prediction(
            prediction,
            thread_id=f"private-thread-{index}",
            reply_message_id=f"private-reply-{index}",
            observed_message_id=f"private-observed-{index}",
            observed_at=observed_at,
        )
        wrong_thread_rejected = not social.observation_matches_prediction(
            prediction,
            thread_id=f"wrong-thread-{index}",
            reply_message_id=f"private-reply-{index}",
            observed_message_id=f"private-observed-{index}",
            observed_at=observed_at,
        )
        case_passed = bool(
            observed_class == expected_class
            and intact.get("scored")
            and lesion.get("scored")
            and lineage_ok
            and wrong_thread_rejected
            and prediction.get("authority") == "observation_and_calibration_only"
            and "private mental-state" in str(prediction.get("boundary") or "")
        )
        intact_loss = float(intact.get("normalized_brier") or 0.0)
        lesioned_loss = float(lesion.get("normalized_brier") or 0.0)
        intact_losses.append(intact_loss)
        lesioned_losses.append(lesioned_loss)
        evidence_id = f"private-social-evidence-{index}"
        feedback_records.append(
            {
                "kind": "conversational",
                "evidence_id": evidence_id,
                "observed_text": raw.get("observed_text"),
                "social_outcome": intact,
            }
        )
        fingerprint = hashlib.sha256(
            json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:20]
        aggregate_cases.append(
            {
                "case_index": index + 1,
                "case_fingerprint": fingerprint,
                "passed": case_passed,
                "intact_normalized_brier": round(intact_loss, 6),
                "lesioned_normalized_brier": round(lesioned_loss, 6),
            }
        )

    intact_mean = sum(intact_losses) / len(intact_losses)
    lesioned_mean = sum(lesioned_losses) / len(lesioned_losses)
    improvement = lesioned_mean - intact_mean
    feedback = social.summarize_records(feedback_records)
    feedback_lesion = social.summarize_records(
        feedback_records, feedback_lesioned=True
    )
    feedback_ok = bool(
        feedback.get("scored_count") == len(cases)
        and feedback_lesion.get("scored_count") == 0
        and feedback.get("contains_user_text") is False
        and feedback.get("contains_private_mental_state") is False
    )
    negative_controls = {
        "incidental_wrong_not_correction": not social.explicitly_corrects_prior_reply(
            "What is wrong with the server?"
        ),
        "explicit_reply_correction_detected": social.explicitly_corrects_prior_reply(
            "No, your answer is wrong."
        ),
        "feedback_text_free": feedback_ok,
    }
    passed = bool(
        all(item["passed"] for item in aggregate_cases)
        and improvement >= threshold
        and all(negative_controls.values())
    )
    return {
        "schema_version": RESULT_SCHEMA,
        "tested_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "passed" if passed else "failed",
        "passed": passed,
        "cases_passed": sum(1 for item in aggregate_cases if item["passed"]),
        "cases_total": len(aggregate_cases),
        "intact_mean_normalized_brier": round(intact_mean, 6),
        "lesioned_mean_normalized_brier": round(lesioned_mean, 6),
        "mean_brier_improvement": round(improvement, 6),
        "minimum_mean_brier_improvement": round(threshold, 6),
        "feedback_evidence_count": int(feedback.get("scored_count") or 0),
        "feedback_lesion_evidence_count": int(
            feedback_lesion.get("scored_count") or 0
        ),
        "negative_controls": negative_controls,
        "cases": aggregate_cases,
        "privacy": {
            "private_fixture_text_retained": False,
            "raw_user_text_retained": False,
            "private_mental_state_retained": False,
        },
        "boundary": BOUNDARY,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True)
    parser.add_argument("--registration", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    spec_path = Path(args.spec).expanduser().resolve()
    registration_path = Path(args.registration).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    evaluator_path = Path(__file__).resolve()
    try:
        spec = _load_json(spec_path)
        registration = _load_json(registration_path)
        hashes = _validate_registration(
            registration,
            spec_path=spec_path,
            evaluator_path=evaluator_path,
            module_path=ROOT / "eve_social_prediction.py",
            integration_path=ROOT / "eve.py",
            kernel_path=ROOT / "eve_consciousness.py",
        )
        result = run(spec)
        result["validated_sha256"] = hashes
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["passed"] else 1
    except Exception as exc:
        failure = {
            "schema_version": RESULT_SCHEMA,
            "tested_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "status": "infrastructure_failed",
            "passed": False,
            "reason": str(exc),
            "privacy": {
                "private_fixture_text_retained": False,
                "raw_user_text_retained": False,
                "private_mental_state_retained": False,
            },
            "boundary": BOUNDARY,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(failure, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(failure, indent=2, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
