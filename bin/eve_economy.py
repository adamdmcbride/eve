#!/usr/bin/env python3
"""Standalone proposal-only economy CLI for Eve."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eve_economy import main


if __name__ == "__main__":
    raise SystemExit(main())
