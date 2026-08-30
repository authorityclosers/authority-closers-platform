"""Telemetry recorder that redacts before crossing the sink boundary."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from ac_platform.telemetry.models import TelemetryCategory, TelemetryEvent, TelemetrySink


class TelemetryRecorder:
    """Record safe telemetry without exposing audit storage or provider secrets."""

    def __init__(self, sink: TelemetrySink) -> None:
        self._sink = sink

    def emit(
        self,
        name: str,
        attributes: Mapping[str, Any] | None = None,
        *,
        category: TelemetryCategory | str = TelemetryCategory.PRODUCT,
        tenant_id: UUID | None = None,
        occurred_at: datetime | None = None,
    ) -> TelemetryEvent:
        event = TelemetryEvent(
            name=name,
            attributes=attributes or {},
            category=category,
            tenant_id=tenant_id,
            occurred_at=occurred_at or datetime.now(UTC),
        )
        self._sink.record(event)
        return event

    def record(self, event: TelemetryEvent) -> TelemetryEvent:
        """Record a prebuilt event; construction already enforces redaction."""

        self._sink.record(event)
        return event


__all__ = ["TelemetryRecorder"]
