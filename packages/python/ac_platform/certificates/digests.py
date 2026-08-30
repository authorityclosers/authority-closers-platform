"""Canonical certificate payload encoding shared with PostgreSQL invariants."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from decimal import Decimal
from typing import Any


def canonical_json(value: Any) -> str:
    """Encode JSON data deterministically using the database's normalization rules."""

    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("certificate digest payload numbers must be finite")
        if value == 0:
            return "0.0"
        return format(Decimal(str(value)), "f")
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("certificate digest payload object keys must be strings")
        entries = (f"{canonical_json(key)}:{canonical_json(value[key])}" for key in sorted(value))
        return "{" + ",".join(entries) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(canonical_json(item) for item in value) + "]"
    raise TypeError(f"unsupported certificate digest payload value: {type(value).__name__}")


def canonical_sha256(payload: Mapping[str, Any]) -> str:
    """Return the lowercase SHA-256 digest for a canonical JSON object."""

    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
