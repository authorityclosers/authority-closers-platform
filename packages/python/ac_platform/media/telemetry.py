"""Redacted media operational telemetry boundary.

Media telemetry is an observation channel.  It never writes learning
progress, completion, access, or playback evidence.  Export failures are
fail-soft by default so an exporter outage cannot turn a safe media operation
into a canonical state mutation or rollback decision.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from ac_platform.telemetry.redaction import redact, sanitize_error

_EVENT_NAME = re.compile(r"^media\.[a-z][a-z0-9_.-]{0,127}$")
_OPERATION = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_SAFE_WORD = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")
_OUTCOMES = frozenset({"succeeded", "failed", "retryable", "blocked", "skipped"})
_STATUSES = frozenset(
    {"unconfigured", "configured", "queued", "processing", "ready", "failed", "retired"}
)
_PROTOCOLS = frozenset({"hls", "progressive", "upload", "read"})


@dataclass(frozen=True, slots=True)
class MediaTelemetryEvent:
    """Low-cardinality media event safe to send to an approved exporter."""

    name: str
    operation: str
    outcome: str
    status: str | None = None
    protocol: str | None = None
    duration_ms: int | None = None
    bytes_processed: int | None = None
    rendition_count: int | None = None
    reason_code: str | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    event_id: UUID = field(default_factory=uuid4, repr=False)

    def __post_init__(self) -> None:
        name = self.name.strip()
        operation = self.operation.strip().lower()
        outcome = self.outcome.strip().lower()
        status = self.status.strip().lower() if self.status is not None else None
        protocol = self.protocol.strip().lower() if self.protocol is not None else None
        reason_code = self.reason_code.strip().lower() if self.reason_code is not None else None
        if not _EVENT_NAME.fullmatch(name):
            raise ValueError("media telemetry event name is invalid")
        if not _OPERATION.fullmatch(operation):
            raise ValueError("media telemetry operation is invalid")
        if outcome not in _OUTCOMES:
            raise ValueError("media telemetry outcome is invalid")
        if status is not None and status not in _STATUSES:
            raise ValueError("media telemetry status is invalid")
        if protocol is not None and protocol not in _PROTOCOLS:
            raise ValueError("media telemetry protocol is invalid")
        if reason_code is not None and not _SAFE_WORD.fullmatch(reason_code):
            raise ValueError("media telemetry reason code is invalid")
        for field_name, value, maximum in (
            ("duration_ms", self.duration_ms, 86_400_000),
            ("bytes_processed", self.bytes_processed, 64 * 1024 * 1024 * 1024),
            ("rendition_count", self.rendition_count, 16),
        ):
            if value is not None and (isinstance(value, bool) or value < 0 or value > maximum):
                raise ValueError(f"media telemetry {field_name} is outside the bounded limit")
        occurred_at = self.occurred_at
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("media telemetry time must be timezone-aware")
        if not isinstance(self.event_id, UUID):
            raise TypeError("media telemetry event_id must be a UUID")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "outcome", outcome)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "protocol", protocol)
        object.__setattr__(self, "reason_code", reason_code)
        object.__setattr__(self, "occurred_at", occurred_at.astimezone(UTC))

    def as_record(self) -> dict[str, object]:
        """Return a JSON-safe record without object keys, URLs, or secrets."""

        record = asdict(self)
        record["event_id"] = str(self.event_id)
        record["occurred_at"] = self.occurred_at.isoformat()
        return record


class MediaTelemetryExporter(Protocol):
    """Exporter port implemented by OTel or a worker-owned sink."""

    def export(self, event: MediaTelemetryEvent) -> None: ...


class NullMediaTelemetryExporter:
    """Explicit no-export sink used before observability composition."""

    def export(self, event: MediaTelemetryEvent) -> None:
        del event


class InMemoryMediaTelemetryExporter:
    """Safe local/test exporter; it never performs network I/O."""

    def __init__(self) -> None:
        self.events: list[MediaTelemetryEvent] = []

    def export(self, event: MediaTelemetryEvent) -> None:
        self.events.append(event)


class JsonlMediaTelemetryExporter:
    """Best-effort append-oriented local sink for tests and inspection.

    A flush is not a durability or crash-consistency guarantee; production
    retention and telemetry evidence require an explicitly composed sink.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if self.path.exists() and not self.path.is_file():
            raise ValueError("media telemetry path must be a file")

    def export(self, event: MediaTelemetryEvent) -> None:
        # Re-validate through the conservative redactor before writing.  The
        # event schema already excludes identifiers/URLs, while this guard
        # prevents future fields from turning the local sink into a data dump.
        record = redact(
            {
                "operation": event.operation,
                "outcome": event.outcome,
                "status": event.status,
                "protocol": event.protocol,
                "duration_ms": event.duration_ms,
                "bytes_processed": event.bytes_processed,
                "rendition_count": event.rendition_count,
                "reason_code": event.reason_code,
            }
        )
        if not isinstance(record, dict):  # pragma: no cover - redact preserves mappings
            raise TypeError("media telemetry record must be a mapping")
        record.update(
            {
                "name": event.name,
                "event_id": str(event.event_id),
                "occurred_at": event.occurred_at.isoformat(),
            }
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            stream.flush()


class MediaTelemetryRecorder:
    """Record media observations without making them canonical facts."""

    def __init__(
        self,
        exporter: MediaTelemetryExporter | None = None,
        *,
        fail_soft: bool = True,
    ) -> None:
        self.exporter = exporter or NullMediaTelemetryExporter()
        if not isinstance(fail_soft, bool):
            raise TypeError("media telemetry fail_soft must be a boolean")
        self.fail_soft = fail_soft
        self.last_export_error: str | None = None

    def emit(
        self,
        name: str,
        *,
        operation: str,
        outcome: str,
        status: str | None = None,
        protocol: str | None = None,
        duration_ms: int | None = None,
        bytes_processed: int | None = None,
        rendition_count: int | None = None,
        reason_code: str | None = None,
        occurred_at: datetime | None = None,
    ) -> MediaTelemetryEvent:
        event = MediaTelemetryEvent(
            name=name,
            operation=operation,
            outcome=outcome,
            status=status,
            protocol=protocol,
            duration_ms=duration_ms,
            bytes_processed=bytes_processed,
            rendition_count=rendition_count,
            reason_code=reason_code,
            occurred_at=occurred_at or datetime.now(UTC),
        )
        try:
            self.exporter.export(event)
        except Exception as error:
            if not self.fail_soft:
                raise
            # Keep a bounded diagnostic available to the caller without
            # writing provider/credential details into logs automatically.
            self.last_export_error = sanitize_error(error, max_length=256)
        return event

    def record(self, event: MediaTelemetryEvent) -> MediaTelemetryEvent:
        if not isinstance(event, MediaTelemetryEvent):
            raise TypeError("media telemetry recorder accepts MediaTelemetryEvent")
        try:
            self.exporter.export(event)
        except Exception as error:
            if not self.fail_soft:
                raise
            self.last_export_error = sanitize_error(error, max_length=256)
        return event


__all__ = [
    "InMemoryMediaTelemetryExporter",
    "JsonlMediaTelemetryExporter",
    "MediaTelemetryEvent",
    "MediaTelemetryExporter",
    "MediaTelemetryRecorder",
    "NullMediaTelemetryExporter",
]
