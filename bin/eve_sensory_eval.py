#!/usr/bin/env python3
"""Run Eve's deterministic selective-perception evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_sensory_eval  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate Eve's selective perception without opening sensors or mutating lived state."
    )
    parser.add_argument(
        "--hours",
        type=float,
        default=4.0,
        help="Accelerated simulated duration in hours (default: 4).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON artifact path.",
    )
    args = parser.parse_args()
    if args.hours <= 0 or args.hours > 168:
        parser.error("--hours must be greater than 0 and no more than 168")
    report = eve_sensory_eval.run_evaluation(duration_hours=args.hours)
    rendered = json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
