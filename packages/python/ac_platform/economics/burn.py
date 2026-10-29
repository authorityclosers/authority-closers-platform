"""The measured allocation keys: agent work per project and the ac server's time.

``agent-burn.json`` sits at the metrics store's root. It is written nightly by
``ac-agent-burn`` on the ac server (infra/vps-foundation/scripts/ac-agent-burn.py) from the
agents' own session logs, with a laptop's summary added when one is sent. It holds counts
only: list-price weighted tokens per area of work for each tool, and the CPU shares of the
apps, the agents' slice and everything else. No prompt, file or person is in it.

A missing, unreadable or malformed file gives no keys; costs that need one stay with the
company until it is measured.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

FILE = "agent-burn.json"
MAX_BYTES = 256 * 1024


def _weights(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    found: dict[str, float] = {}
    for key, value in raw.items():
        if (
            isinstance(key, str)
            and len(key) <= 40
            and isinstance(value, int | float)
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value > 0
        ):
            found[key] = float(value)
    return found


def parse(raw: Any) -> dict[str, Any] | None:
    """The file's keys as {generated_at, window_days, tokens: {tool: {area: weight}},
    sources: {tool: {source: when}}, cpu: {apps, agents, other} | None}, or None."""
    if not isinstance(raw, dict) or raw.get("version") != 1:
        return None
    tools = raw.get("tools")
    if not isinstance(tools, dict):
        return None
    tokens: dict[str, dict[str, float]] = {}
    sources: dict[str, dict[str, str]] = {}
    for tool in ("claude", "codex"):
        entry = tools.get(tool)
        if not isinstance(entry, dict):
            continue
        areas = _weights(entry.get("areas"))
        if areas:
            tokens[tool] = areas
            seen = entry.get("sources")
            sources[tool] = (
                {str(k)[:40]: str(v)[:40] for k, v in seen.items()}
                if isinstance(seen, dict)
                else {}
            )
    cpu = _weights(raw.get("cpu"))
    window = raw.get("window_days")
    return {
        "generated_at": str(raw.get("generated_at") or "")[:40] or None,
        "window_days": window if isinstance(window, int) and 0 < window <= 90 else None,
        "tokens": tokens,
        "sources": sources,
        "cpu": {key: cpu[key] for key in ("apps", "agents", "other") if key in cpu} or None,
    }


def read(root: str | None) -> dict[str, Any] | None:
    """The keys from ``root``'s file (blocking: call it off the event loop)."""
    if not root:
        return None
    path = Path(root) / FILE
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        return parse(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None
