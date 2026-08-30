from __future__ import annotations

from uuid import uuid4

import pytest

from ac_platform.telemetry import (
    REDACTED,
    InMemoryTelemetrySink,
    TelemetryCategory,
    TelemetryEvent,
    TelemetryRecorder,
    redact_attributes,
    sanitize_error,
)


def test_redaction_removes_secrets_email_phone_ip_and_payment_card_shapes() -> None:
    source = {
        "person_id": "person-1",
        "email": "learner@example.test",
        "headers": {"Authorization": "Bearer super-secret-token"},
        "nested": [{"access_token": "token-value"}],
        "message": (
            "provider sk_live_123456789 called +1 (415) 555-2671 from 203.0.113.9 "
            "and fe80::1 with card 4111 1111 1111 1111 for learner@example.test"
        ),
    }

    redacted = redact_attributes(source)

    assert redacted["person_id"] == "person-1"
    assert redacted["email"] == REDACTED
    assert redacted["headers"] == {"Authorization": REDACTED}
    assert redacted["nested"] == [{"access_token": REDACTED}]
    for sensitive in (
        "sk_live_123456789",
        "415",
        "203.0.113.9",
        "fe80::1",
        "4111",
        "learner@example.test",
    ):
        assert sensitive not in redacted["message"]
    assert source["email"] == "learner@example.test"


def test_telemetry_recorder_accepts_only_safe_low_cardinality_attributes() -> None:
    sink = InMemoryTelemetrySink()
    event = TelemetryRecorder(sink).emit(
        "worker.job.retry_wait",
        {
            "job_kind": "email.enrollment_welcome.v1",
            "attempt": 2,
            "outcome": "retry_wait",
            "error_code": "provider_error",
        },
        category=TelemetryCategory.OPERATIONAL,
    )

    assert sink.events == [event]
    assert event.attributes["job_kind"] == "email.enrollment_welcome.v1"
    assert event.category is TelemetryCategory.OPERATIONAL


@pytest.mark.parametrize("identifier_key", ["job_id", "person_id", "request_id", "trace_id"])
def test_arbitrary_identifier_attributes_are_rejected(identifier_key: str) -> None:
    with pytest.raises(ValueError, match="not allowlisted"):
        TelemetryEvent(
            name="worker.job.failed",
            attributes={identifier_key: str(uuid4())},
        )


def test_tenant_identifier_field_is_rejected_as_high_cardinality() -> None:
    with pytest.raises(ValueError, match="high-cardinality tenant"):
        TelemetryEvent(
            name="worker.job.failed",
            attributes={"outcome": "failed"},
            tenant_id=uuid4(),
        )


def test_identifier_shaped_values_cannot_hide_under_safe_categorical_keys() -> None:
    # Redaction can conservatively replace a digit-heavy UUID before the
    # categorical vocabulary check. Either bounded guard must reject it.
    with pytest.raises(ValueError, match=r"bounded (?:scalar values|vocabulary)"):
        TelemetryEvent(
            name="worker.job.failed",
            attributes={"status": str(uuid4())},
        )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("status", "status-unknown-123"),
        ("provider", "provider-" + str(uuid4())),
        ("error_code", "provider_error_" + str(uuid4())),
        ("job_kind", "email.custom_job.v1"),
        ("event_type", "delivery.custom"),
        ("release_channel", "production-" + str(uuid4())),
    ],
)
def test_every_categorical_attribute_rejects_unbounded_values(key: str, value: str) -> None:
    with pytest.raises(ValueError, match="bounded vocabulary"):
        TelemetryEvent(name="worker.job.failed", attributes={key: value})


def test_known_categorical_values_remain_accepted() -> None:
    event = TelemetryEvent(
        name="worker.job.failed",
        attributes={
            "activity_kind": "video",
            "communication_class": "enrollment_welcome_next_action",
            "error_code": "provider_error",
            "event_type": "delivery.accepted",
            "job_kind": "email.enrollment_welcome.v1",
            "outcome": "retry_wait",
            "provider": "fake-email",
            "release_channel": "production",
            "status": "ready",
        },
    )
    assert event.attributes["status"] == "ready"


def test_audit_events_are_not_accepted_as_telemetry() -> None:
    with pytest.raises(ValueError, match="not product or operational telemetry"):
        TelemetryEvent(
            name="audit.job.retry.v1",
            attributes={},
            category=TelemetryCategory.OPERATIONAL,
        )
    with pytest.raises(ValueError, match="not product or operational telemetry"):
        TelemetryEvent(name="job.retry", attributes={}, category="audit")


def test_telemetry_attributes_are_immutable_and_bounded() -> None:
    event = TelemetryEvent(name="worker.job.failed", attributes={"attempt": 1})

    with pytest.raises(TypeError):
        event.attributes["attempt"] = 2  # type: ignore[index]
    with pytest.raises(ValueError, match="bounded attribute count"):
        TelemetryEvent(
            name="worker.job.failed",
            attributes={f"key_{index}": index for index in range(33)},
        )
    with pytest.raises(ValueError, match="bounded scalar values"):
        TelemetryEvent(
            name="worker.job.failed",
            attributes={"status": [str(index) for index in range(17)]},
        )
    with pytest.raises(ValueError, match="bounded scalar values"):
        TelemetryEvent(name="worker.job.failed", attributes={"duration_ms": float("nan")})
    with pytest.raises(ValueError, match="bounded schema"):
        TelemetryEvent(name="Worker Job Failed", attributes={})


def test_error_sanitization_is_bounded_and_removes_provider_pii() -> None:
    sanitized = sanitize_error(
        "Authorization: Bearer very-secret-token user@example.test 2001:db8::1 +44 20 7946 0958",
        max_length=64,
    )

    assert "very-secret-token" not in sanitized
    assert "user@example.test" not in sanitized
    assert "2001:db8::1" not in sanitized
    assert "7946" not in sanitized
    assert len(sanitized) <= 64
