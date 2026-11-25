#!/usr/bin/env python3
"""Build a validity-centered Eve consciousness-evidence dossier."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_consciousness_evidence as evidence  # noqa: E402


MAX_MANIFEST_BYTES = 2 * 1024 * 1024


def _load(path_value: str):
    path = Path(path_value).expanduser()
    if path.is_symlink() or not path.is_file():
        raise ValueError("manifest must be a regular non-symlink file")
    if path.stat().st_size <= 0 or path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("manifest must be non-empty and at most 2 MiB")
    return json.loads(path.read_text(encoding="utf-8"))


def _write(payload, path_value: str) -> None:
    rendered = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    if path_value:
        destination = Path(path_value).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(destination)
    sys.stdout.write(rendered)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate four separate consciousness-evidence streams without "
            "emitting a scalar score, probability, or binary verdict."
        )
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    result = evidence.build_dossier(_load(args.manifest))
    _write(result, args.output or "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
