#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time

PROFILE_CHOICES = {"user_relational", "user_general", "system_internal"}


def extract_json_object(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def normalize_profile(value: object) -> str:
    profile = str(value or "").strip().lower()
    if profile not in PROFILE_CHOICES:
        return ""
    return profile


def build_router_prompt(message: str) -> str:
    return (
        "You are routing Eve's support context for one user turn.\n"
        "Choose exactly one profile and return exactly JSON with keys profile and reason.\n"
        "Profiles:\n"
        "- user_relational: the user wants a human, caring, trust-repair, emotional, or tone-sensitive reply. Keep internal system/project/runtime context out of the answer.\n"
        "- user_general: the user wants a normal outward-facing answer or task help. Keep context light and avoid internal runtime narration.\n"
        "- system_internal: the user is explicitly asking about models, runtime, architecture, routing, tooling, performance, memory systems, or implementation details.\n"
        'Example: {"profile":"user_relational","reason":"user is asking about tone and human presence, not internals"}\n'
        f"Message: {message.strip()}"
    )


def cmd_route(args: argparse.Namespace) -> int:
    prompt = build_router_prompt(args.message)
    started = time.perf_counter()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mlx_lm",
            "generate",
            "--model",
            args.model,
            "--prompt",
            prompt,
            "--max-tokens",
            str(args.max_tokens),
            "--temp",
            "0",
            "--verbose",
            "False",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    total_seconds = time.perf_counter() - started
    raw_output = result.stdout.strip()
    parsed = extract_json_object(raw_output)
    profile = normalize_profile(parsed.get("profile") if parsed else "")
    reason = str(parsed.get("reason") or "").strip() if parsed else ""
    ok = bool(result.returncode == 0 and profile)
    print(
        json.dumps(
            {
                "ok": ok,
                "model": args.model,
                "total_seconds": round(total_seconds, 3),
                "profile": profile,
                "reason": reason,
                "raw_output": raw_output,
                "stderr_tail": "\n".join(
                    line for line in result.stderr.strip().splitlines()[-4:] if line
                ),
            },
            indent=2,
        )
    )
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Route Eve turn context with a small local MLX model.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    route_parser = subparsers.add_parser("route", help="Classify one turn into a context profile.")
    route_parser.add_argument("--model", required=True, help="HF repo or local MLX model path.")
    route_parser.add_argument("--message", required=True, help="The user turn to classify.")
    route_parser.add_argument("--max-tokens", type=int, default=80, help="Max tokens for the router output.")
    route_parser.set_defaults(func=cmd_route)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
