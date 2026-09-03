"""Compatibility import surface for telemetry callers."""

from ac_platform.telemetry.models import InMemoryTelemetrySink, TelemetryCategory, TelemetryEvent
from ac_platform.telemetry.redaction import (
    REDACTED,
    freeze_attributes,
    redact,
    redact_attributes,
    sanitize_error,
)
from ac_platform.telemetry.service import TelemetryRecorder

__all__ = [
    "InMemoryTelemetrySink",
    "REDACTED",
    "TelemetryCategory",
    "TelemetryEvent",
    "TelemetryRecorder",
    "freeze_attributes",
    "redact",
    "redact_attributes",
    "sanitize_error",
]
