#!/usr/bin/env python3
"""Compatibility wrapper for Eve Chat's local UI server."""

from __future__ import annotations

from eve_chat_local_serve import main  # noqa: F401


if __name__ == "__main__":
    raise SystemExit(main())
