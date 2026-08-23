#!/usr/bin/env python3
"""Register or score Eve consciousness-indicator interventions."""

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_consciousness_protocol as protocol  # noqa: E402


def _load(path: str):
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def _write(payload, path: str) -> None:
    rendered = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    if path:
        destination = Path(path).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preregister or score theory-specific indicators without issuing a consciousness verdict."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--register", metavar="DRAFT_JSON")
    group.add_argument("--score", metavar="REGISTRATION_JSON")
    parser.add_argument("--evidence", help="Evidence JSON array; required with --score.")
    parser.add_argument("--scored-by", default="independent_operator")
    parser.add_argument("--scored-at")
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.register:
        result = protocol.preregister(_load(args.register))
    else:
        if not args.evidence or not args.scored_at:
            parser.error("--score requires --evidence and --scored-at")
        result = protocol.score_protocol(
            _load(args.score),
            _load(args.evidence),
            scored_by=args.scored_by,
            scored_at=args.scored_at,
        )
    _write(result, args.output or "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

