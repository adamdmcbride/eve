"""Read-only Dagster lab assets over Eve evidence artifacts.

This module is deliberately outside Eve's daemon, scheduler, governance, and
action paths. It materializes summaries from existing `.eve` artifacts only.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict

from dagster import AssetCheckResult, Definitions, MetadataValue, asset, asset_check


ROOT = Path(__file__).resolve().parents[1]
EVE_DIR = ROOT / ".eve"
DAGSTER_LAB_DIR = EVE_DIR / "dagster_lab"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_summary(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@asset(description="Summary of Eve's latest whole-system and consciousness evidence artifacts.")
def latest_eve_evidence_summary() -> Dict[str, Any]:
    whole_system_path = EVE_DIR / "whole_system_evals" / "latest.json"
    consciousness_path = EVE_DIR / "capability_tests" / "latest_consciousness_test.json"
    whole_system = read_json(whole_system_path)
    consciousness = read_json(consciousness_path)
    consciousness_rank = consciousness.get("rank") if isinstance(consciousness.get("rank"), dict) else {}
    summary = {
        "generated_at": utc_now(),
        "whole_system": {
            "path": str(whole_system_path),
            "present": bool(whole_system),
            "status": whole_system.get("status") or "missing",
            "checks": whole_system.get("checks"),
            "failing": whole_system.get("failing"),
        },
        "consciousness_evidence": {
            "path": str(consciousness_path),
            "present": bool(consciousness),
            "passed": bool(consciousness.get("passed")),
            "verdict": consciousness.get("verdict") or "missing",
            "average_score": consciousness_rank.get("average_score"),
            "minimum_score": consciousness_rank.get("minimum_score"),
        },
        "authority_boundary": "Dagster lab reads existing evidence artifacts only; it does not schedule Eve, approve proposals, send messages, promote models, or write memory.",
    }
    write_summary(DAGSTER_LAB_DIR / "latest_eve_evidence_summary.json", summary)
    return summary


@asset_check(asset=latest_eve_evidence_summary, description="Evidence summary should find at least one live Eve evidence artifact.")
def latest_eve_evidence_summary_has_source(latest_eve_evidence_summary: Dict[str, Any]) -> AssetCheckResult:
    whole_system = latest_eve_evidence_summary.get("whole_system")
    consciousness = latest_eve_evidence_summary.get("consciousness_evidence")
    whole_present = isinstance(whole_system, dict) and bool(whole_system.get("present"))
    consciousness_present = isinstance(consciousness, dict) and bool(consciousness.get("present"))
    return AssetCheckResult(
        passed=whole_present or consciousness_present,
        metadata={
            "whole_system_present": MetadataValue.bool(whole_present),
            "consciousness_present": MetadataValue.bool(consciousness_present),
        },
    )


defs = Definitions(
    assets=[latest_eve_evidence_summary],
    asset_checks=[latest_eve_evidence_summary_has_source],
)

