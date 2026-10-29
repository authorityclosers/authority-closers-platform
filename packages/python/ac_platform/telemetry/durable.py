"""Fsync-before-ack raw analytics journal. Analytics never authorize product state."""

from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from ac_platform.telemetry.ingest import LEARNER_SURFACE, check_payload_values
from ac_platform.telemetry.sales_xray import SALES_XRAY_SURFACE

ROOT = Path("/var/lib/ac-telemetry")
MAX_BYTES = 1024**3
SEGMENT_BYTES = 16 * 1024**2
RESERVE_BYTES = 64 * 1024**2
# No headers, URLs, names, typed content, IP addresses or raw call IDs.
FIELDS = (
    "event_id",
    "tenant_id",
    "actor_person_id",
    "subject_person_id",
    "event_name",
    "event_version",
    "event_class",
    "occurred_at",
    "trace_id",
    "release_id",
    "session_id",
    "route",
    "period",
    "payload",
    "consent_status",
    "consent_purpose",
    "consent_policy_version",
    "consent_captured_at",
    "retention_policy_id",
    "retention_expires_at",
    "created_at",
)


class SpoolUnavailable(OSError):
    """The raw journal could not durably accept a batch; caller must retry."""


def root_for(environment: str) -> Path:
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", environment):
        raise SpoolUnavailable("invalid telemetry environment")
    if environment in {"development", "development-live"}:
        environment = "dev"
    # Dev already binds this durable host directory writable under ProtectSystem.
    default = (
        ROOT
        if environment != "dev"
        else Path("/srv/authority-closers/sales-xray/development-live/telemetry")
    )
    # Explicit mount/config override, no fallback to ephemeral /tmp in deployments.
    return Path(os.environ.get("AC_TELEMETRY_SPOOL_ROOT", str(default))) / environment


def sync_directory(root: Path) -> None:
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def locked(root: Path) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / ".lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def project(event: Any) -> dict[str, Any]:
    """Only validated AnalyticsEvent fields; never serialize an ORM object generically."""
    definition = SALES_XRAY_SURFACE.events.get(event.event_name) or LEARNER_SURFACE.events.get(
        event.event_name
    )
    if definition is None or set(event.payload) - set(definition.allowed_payload_keys):
        raise SpoolUnavailable("raw journal event schema invalid")
    try:
        check_payload_values(definition, event.payload)
    except ValueError as error:
        raise SpoolUnavailable("raw journal payload invalid") from error
    result = {}
    for field in FIELDS:
        value = getattr(event, field)
        if isinstance(value, datetime):
            value = value.isoformat()
        elif field in {"tenant_id", "actor_person_id", "subject_person_id"}:
            value = str(value)
        result[field] = value
    return result


def repair_tail(fd: int) -> int:
    """Discard only a killed writer's unacknowledged final fragment."""
    end = os.lseek(fd, 0, os.SEEK_END)
    if end and os.pread(fd, 1, end - 1) != b"\n":
        tail = os.pread(fd, min(end, 1024 * 1024), max(0, end - 1024 * 1024))
        newline = tail.rfind(b"\n")
        end = max(0, end - len(tail)) + newline + 1 if newline >= 0 else 0
        os.ftruncate(fd, end)
        os.fsync(fd)
    return end


def _close_old(root: Path, hour: str) -> None:
    for path in root.glob("*.open"):
        if not path.name.startswith(hour + "-"):
            fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
            try:
                repair_tail(fd)
            finally:
                os.close(fd)
            path.rename(path.with_suffix(".ndjson"))
    sync_directory(root)


def append(
    root: Path,
    events: list[Any],
    *,
    now: datetime | None = None,
    max_bytes: int = MAX_BYTES,
    reserve_bytes: int = RESERVE_BYTES,
) -> str:
    now = now or datetime.now(UTC)
    hour = now.strftime("%Y-%m-%dT%H")
    receipt = uuid4().hex
    record = {
        "schema": "ac-telemetry-raw/1",
        "receipt": receipt,
        "accepted_at": now.isoformat(),
        "events": [project(event) for event in events],
    }
    data = (json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n").encode()
    try:
        with locked(root):
            _close_old(root, hour)
            size = sum(p.stat().st_size for p in root.iterdir() if p.is_file())
            # Reserve compression workspace as well as the journal itself.
            if size + len(data) > max_bytes // 2 or shutil.disk_usage(root).free < (
                reserve_bytes + 2 * len(data)
            ):
                raise SpoolUnavailable("telemetry spool full")
            host = re.sub(r"[^a-zA-Z0-9-]", "-", socket.gethostname())[:48]
            candidates = sorted(root.glob(f"{hour}-{host}-*.open"))
            path = candidates[-1] if candidates else root / f"{hour}-{host}-{uuid4().hex}.open"
            if path.exists() and path.stat().st_size + len(data) > SEGMENT_BYTES:
                path.rename(path.with_suffix(".ndjson"))
                path = root / f"{hour}-{host}-{uuid4().hex}.open"
            fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_APPEND | os.O_NOFOLLOW, 0o600)
            try:
                start = os.lseek(fd, 0, os.SEEK_END)
                start = repair_tail(fd)
                try:
                    remaining = memoryview(data)
                    while remaining:
                        written = os.write(fd, remaining)
                        if written <= 0:
                            raise SpoolUnavailable("telemetry short append")
                        remaining = remaining[written:]
                    os.fsync(fd)
                except BaseException:
                    os.ftruncate(fd, start)
                    os.fsync(fd)
                    raise
            finally:
                os.close(fd)
            sync_directory(root)
    except OSError as error:
        raise SpoolUnavailable("telemetry durable append failed") from error
    return receipt


def close_hours(root: Path, now: datetime | None = None) -> list[Path]:
    with locked(root):
        _close_old(root, (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H"))
        return sorted(root.glob("*.ndjson"))


def day_inventory(root: Path, day: str) -> dict[str, Any]:
    """Union event IDs, including verified-upload receipts kept after local deletion."""
    ids: set[str] = set()
    batches = 0
    for path in sorted(root.glob("*")):
        if path.suffix in {".open", ".ndjson"}:
            try:
                with path.open() as handle:
                    for line in handle:
                        if not line.endswith("\n"):
                            break  # Concurrent append, not yet acknowledged.
                        row = json.loads(line)
                        for event in row["events"]:
                            if event["occurred_at"][:10] == day:
                                ids.add(f"{event['tenant_id']}:{event['event_id']}")
                                batches += 1
            except FileNotFoundError:
                receipt = path.with_suffix(".receipt")
                row = json.loads(receipt.read_text())
                ids.update(row.get("days", {}).get(day, []))
        elif path.suffix == ".receipt":
            row = json.loads(path.read_text())
            ids.update(row.get("days", {}).get(day, []))
    return {"events": len(ids), "observations": batches, "event_ids": sorted(ids)}
