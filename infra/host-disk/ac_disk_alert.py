#!/usr/bin/env python3
"""Read-only disk check; --apply sends threshold alerts through existing ac-notify.

Also (16 Nov 2026): each staging and production native helper's C1 image (``--image-ref`` in
its systemd unit) must be present in Docker; a missing one means every upload fails its audio
check. One alert when one goes missing, one when it is back.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import re
import subprocess
from pathlib import Path

STATE = Path("/var/lib/ac-disk-alert/state.json")
NOTIFY = "/usr/local/sbin/ac-notify"
DOCKER = "/usr/bin/docker"
NATIVE_UNITS = Path("/etc/systemd/system")
NATIVE_ENVIRONMENTS = ("staging", "production")
_IMAGE_REF = re.compile(r"--image-ref (sha256:[0-9a-f]{64})")


def native_images(units: Path = NATIVE_UNITS) -> dict[str, bool | None]:
    """Whether each environment's native C1 image is present in Docker (inspect only); None
    (unknown) when Docker gives no answer in time, so the disk alerts still go out."""
    found: dict[str, bool | None] = {}
    for environment in NATIVE_ENVIRONMENTS:
        unit = units / f"ac-sales-xray-native-{environment}.service"
        if not unit.is_file() or unit.is_symlink():
            continue
        match = _IMAGE_REF.search(unit.read_text())
        if match is None:
            continue
        try:
            inspected = subprocess.run(  # noqa: S603 - fixed host executable, a checked digest
                [DOCKER, "image", "inspect", "--format", "{{.Id}}", match.group(1)],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            found[environment] = None
            continue
        found[environment] = inspected.returncode == 0
    return found


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


def _notify(message: str) -> None:
    sent = subprocess.run(  # noqa: S603 - fixed host executable; message goes through stdin
        [NOTIFY], input=message, text=True, capture_output=True, timeout=30, check=False
    )
    if sent.returncode:
        # Do not print notification output: the transport owns credentials.
        raise RuntimeError("disk notification failed; state unchanged for retry")


def check(
    state_path: Path,
    figures: dict[str, int],
    *,
    apply: bool,
    native: dict[str, bool | None] | None = None,
) -> dict:
    previous_missing: list[str] = []
    if state_path.exists():
        state = json.loads(state_path.read_text())
        previous = state["level"]
        if type(previous) is not int or previous not in (0, 85, 95):
            raise ValueError("invalid disk alert state")
        previous_missing = state.get("native_missing", [])
        if not isinstance(previous_missing, list) or not all(
            isinstance(item, str) for item in previous_missing
        ):
            raise ValueError("invalid disk alert state")
    else:
        previous = 0
    level, event = transition(previous, figures["percent"])
    native = native or {}
    # Unknown (Docker gave no answer) keeps what was last known: no alert either way.
    missing = sorted(
        env
        for env, present in native.items()
        if present is False or (present is None and env in previous_missing)
    )
    unknown = sorted(env for env, present in native.items() if present is None)
    gone = [env for env in missing if env not in previous_missing]
    back = [env for env in previous_missing if env not in missing]
    result = {
        **figures,
        "level": level,
        "event": event,
        "applied": apply,
        "native_missing": missing,
        "native_unknown": unknown,
    }
    if not apply:
        return result
    if event:
        free_gib = figures["available_bytes"] / 1024**3
        _notify(
            f"AC server disk {event}: / is {figures['percent']}% used; "
            f"{free_gib:.1f} GiB available. Warning threshold 85%, critical 95%; "
            "checked every 5 minutes. Cleanup task AUT-2165."
        )
    if gone:
        _notify(
            "Sales X-Ray native C1 image missing from Docker on ac for "
            f"{', '.join(gone)}: every upload fails its audio check. Load the stored artifact "
            "(docker load native-image.tar.gz) and name it (docker tag ... ac-sales-xray-native)."
        )
    if back:
        _notify(f"Sales X-Ray native C1 image back in Docker for {', '.join(back)}.")
    temporary = state_path.with_suffix(".new")
    with temporary.open("w") as stream:
        json.dump({"level": level, "last_check": figures, "native_missing": missing}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(state_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        print(
            json.dumps(check(STATE, usage(), apply=False, native=native_images()), sort_keys=True)
        )
        return 0
    STATE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (STATE.parent / "check.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(json.dumps(check(STATE, usage(), apply=True, native=native_images()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
