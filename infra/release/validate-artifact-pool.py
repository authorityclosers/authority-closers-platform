#!/usr/bin/env python3
"""Validate and print the repository-wide GitHub artifact pool allowance."""

from __future__ import annotations

import os
import re
import sys

VARIABLE = "AC_RELEASE_ARTIFACT_POOL_BYTES"
DEFAULT_BYTES = 1_000_000_000
MINIMUM_BYTES = 450_000_000
MAXIMUM_BYTES = 4_000_000_000
MAXIMUM_DECIMAL = str(MAXIMUM_BYTES)


def parse_pool_bytes(raw: str | None) -> int:
    """Return a bounded pool allowance, defaulting only when unset."""

    if raw is None or raw == "":
        return DEFAULT_BYTES
    if re.fullmatch(r"[0-9]+", raw) is None:
        raise ValueError(f"{VARIABLE} must contain decimal digits only")

    # Bound the digit string before converting it. This keeps malformed
    # operator-supplied values from reaching Python's arbitrary-precision
    # conversion path and makes the upper bound check exact.
    normalized = raw.lstrip("0") or "0"
    if len(normalized) > len(MAXIMUM_DECIMAL) or (
        len(normalized) == len(MAXIMUM_DECIMAL) and normalized > MAXIMUM_DECIMAL
    ):
        raise ValueError(f"{VARIABLE} must be between {MINIMUM_BYTES} and {MAXIMUM_BYTES} bytes")

    value = int(normalized)
    if value < MINIMUM_BYTES:
        raise ValueError(f"{VARIABLE} must be between {MINIMUM_BYTES} and {MAXIMUM_BYTES} bytes")
    return value


def main() -> int:
    try:
        value = parse_pool_bytes(os.environ.get(VARIABLE))
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
