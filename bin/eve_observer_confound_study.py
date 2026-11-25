#!/usr/bin/env python3
"""Operate Eve's blinded observer-confound study without exposing assignments."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import sys
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_observer_confound as study  # noqa: E402


def _load(path: Path) -> object:
    if path.is_symlink() or not path.is_file():
        raise ValueError("input must be a regular non-symlink file")
    return json.loads(path.read_text(encoding="utf-8"))


def _write(payload: Mapping[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("refusing to write through a symbolic link")
    rendered = (
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    descriptor = os.open(
        str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
    )
    try:
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, rendered)
    finally:
        os.close(descriptor)
    sys.stdout.write(
        json.dumps(
            {
                "schema_version": payload.get("schema_version"),
                "output": path.name,
                "sha256": study.file_sha256(path),
                "consciousness_verdict": "none",
            },
            sort_keys=True,
        )
        + "\n"
    )


def _registration(args) -> object:
    return _load(Path(args.registration).expanduser())


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Preregister, blind, and aggregate a human observer-confound study. "
            "This tool never emits a consciousness verdict."
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    seed_parser = sub.add_parser("seed", help="Create a private randomization seed")
    seed_parser.add_argument("--output", required=True)

    register_parser = sub.add_parser("register", help="Freeze protocol and stimuli")
    register_parser.add_argument("--protocol", required=True)
    register_parser.add_argument("--stimuli", required=True)
    register_parser.add_argument("--seed-file", required=True)
    register_parser.add_argument("--output", required=True)

    packet_parser = sub.add_parser("packet", help="Create one source-blind packet")
    packet_parser.add_argument("--registration", required=True)
    packet_parser.add_argument("--protocol", required=True)
    packet_parser.add_argument("--stimuli", required=True)
    packet_parser.add_argument("--seed-file", required=True)
    packet_parser.add_argument("--rater", required=True)
    packet_parser.add_argument("--output", required=True)

    score_parser = sub.add_parser("score", help="Aggregate locked packet/rating pairs")
    score_parser.add_argument("--registration", required=True)
    score_parser.add_argument("--protocol", required=True)
    score_parser.add_argument("--stimuli", required=True)
    score_parser.add_argument("--seed-file", required=True)
    score_parser.add_argument("--study-dir", required=True)
    score_parser.add_argument("--output", required=True)

    args = parser.parse_args()
    if args.command == "seed":
        output = Path(args.output).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            raise ValueError("refusing to replace an existing seed")
        descriptor = os.open(str(output), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, secrets.token_bytes(64))
        finally:
            os.close(descriptor)
        sys.stdout.write(
            json.dumps(
                {
                    "seed_created": True,
                    "output": output.name,
                    "secret_printed": False,
                    "consciousness_verdict": "none",
                },
                sort_keys=True,
            )
            + "\n"
        )
        return 0
    protocol_path = Path(args.protocol).expanduser()
    stimuli_path = Path(args.stimuli).expanduser()
    seed_path = Path(args.seed_file).expanduser()
    output = Path(args.output).expanduser()
    if args.command == "register":
        result = study.register(protocol_path, stimuli_path, seed_path)
    elif args.command == "packet":
        result = study.build_packet(
            _registration(args),
            protocol_path,
            stimuli_path,
            seed_path,
            args.rater,
        )
    else:
        packets, ratings = study.load_study_files(Path(args.study_dir).expanduser())
        result = study.score_study(
            _registration(args),
            protocol_path,
            stimuli_path,
            seed_path,
            packets,
            ratings,
        )
    _write(result, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
