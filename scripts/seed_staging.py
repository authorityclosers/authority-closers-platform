#!/usr/bin/env python3
"""Compatibility wrapper for ``python -m ac_platform.seed``."""

from ac_platform.seed.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
