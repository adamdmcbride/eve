#!/usr/bin/env python3

import argparse
import sys
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_web


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Eve's local runtime API server.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind.")
    parser.add_argument("--port", type=int, default=8787, help="Port to bind.")
    parser.add_argument("--open", action="store_true", help="Open Eve in the browser after startup.")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return eve_web.main(host=args.host, port=args.port, open_browser=args.open)


if __name__ == "__main__":
    sys.exit(main())
