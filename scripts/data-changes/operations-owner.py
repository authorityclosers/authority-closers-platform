#!/usr/bin/env python3
"""Thin AUT-828 entrypoint; the implementation also runs from the baked API package."""

from ac_platform.authorization.operator_data_change import main

if __name__ == "__main__":
    raise SystemExit(main())
