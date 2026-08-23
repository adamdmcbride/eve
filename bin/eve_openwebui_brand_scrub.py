#!/usr/bin/env python3
"""Compatibility wrapper for Eve Chat's upstream-branding scrubber.

The active implementation lives in ``eve_chat_brand_scrub.py``.
"""

from __future__ import annotations

from eve_chat_brand_scrub import apply_branding, main  # noqa: F401


if __name__ == "__main__":
    raise SystemExit(main())
