#!/usr/bin/env python3
"""Read-only disk check; --apply sends threshold alerts through existing ac-notify."""

from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import subprocess
from pathlib import Path

STATE = Path("/var/lib/ac-disk-alert/state.json")
NOTIFY = "/usr/local/sbin/ac-notify"


def usage(path: str = "/") -> dict[str, int]:
    stats = os.statvfs(path)
    used = stats.f_blocks - stats.f_bfree
    available = stats.f_bavail
    denominator = used + available
    if denominator <= 0:
        raise ValueError("disk capacity unavailable")
    return {
        "percent": math.ceil(100 * used / denominator),
        "available_bytes": available * stats.f_frsize,
        "total_bytes": stats.f_blocks * stats.f_frsize,
    }


def transition(previous: int, percent: int) -> tuple[int, str | None]:
    if percent < 80:
        return 0, "recovered" if previous else None
    level = 95 if percent >= 95 else 85 if percent >= 85 else 0
    if level > previous:
        return level, "critical" if level == 95 else "warning"
    return previous, None


def check(state_path: Path, figures: dict[str, int], *, apply: bool) -> dict:
    if state_path.exists():
        state = json.loads(state_path.read_text())
        previous = state["level"]
        if type(previous) is not int or previous not in (0, 85, 95):
            raise ValueError("invalid disk alert state")
    else:
        previous = 0
    level, event = transition(previous, figures["percent"])
    result = {**figures, "level": level, "event": event, "applied": apply}
    if not apply:
        return result
    if event:
        free_gib = figures["available_bytes"] / 1024**3
        message = (
            f"AC server disk {event}: / is {figures['percent']}% used; "
            f"{free_gib:.1f} GiB available. Warning threshold 85%, critical 95%; "
            "checked every 5 minutes. Cleanup task AUT-2165."
        )
        sent = subprocess.run(  # noqa: S603 - fixed host executable; message goes through stdin
            [NOTIFY], input=message, text=True, capture_output=True, timeout=30, check=False
        )
        if sent.returncode:
            # Do not print notification output: the transport owns credentials.
            raise RuntimeError("disk notification failed; state unchanged for retry")
    temporary = state_path.with_suffix(".new")
    with temporary.open("w") as stream:
        json.dump({"level": level, "last_check": figures}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(state_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps(check(STATE, usage(), apply=False), sort_keys=True))
        return 0
    STATE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (STATE.parent / "check.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(json.dumps(check(STATE, usage(), apply=True), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
