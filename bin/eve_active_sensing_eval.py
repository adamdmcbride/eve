#!/usr/bin/env python3
"""Run Eve's dependency-free active-sensing causal controls."""

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_active_sensing  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate active sensing without opening sensors or mutating Eve state."
    )
    parser.add_argument("--output", help="Optional path for the JSON report.")
    args = parser.parse_args()
    report = eve_active_sensing.matched_causal_evaluation()
    rendered = json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    if args.output:
        path = Path(args.output).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
