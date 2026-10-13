"""Technical duration boundaries, independent of plan or provider authority."""

from dataclasses import replace
from uuid import UUID

import pytest

from ac_platform.conversation_intelligence.acquisition_sessions import MeasuredSource
from ac_platform.conversation_intelligence.application import ConversationError
from ac_platform.conversation_intelligence.checkpoints import SourceBinding, content_hash
from ac_platform.conversation_intelligence.customer_terminal_receipt import (
    CustomerTerminalFailureReceipt,
    validate_terminal_failure_binding,
)


def receipt(seconds: int) -> CustomerTerminalFailureReceipt:
    return CustomerTerminalFailureReceipt(
        source=SourceBinding(str(UUID(int=1)), str(UUID(int=2)), "a" * 64, "v1"),
        usage_id=str(UUID(int=3)),
        submission_id=str(UUID(int=4)),
        duration_evidence_sha256="b" * 64,
        reserved_seconds=seconds,
        run_id=str(UUID(int=5)),
        recovery_generation=1,
        failure_event_id=str(UUID(int=6)),
        failure_event_sha256="c" * 64,
        completed_at_epoch=1791600000,
    )


@pytest.mark.parametrize("duration_ms", [1, 6_000_000, 6_000_001, 7_199_999, 7_200_000])
def test_measured_duration_retains_exact_milliseconds(duration_ms: int) -> None:
    value = MeasuredSource(UUID(int=4), "a" * 64, duration_ms, "b" * 64)
    assert value.duration_ms == duration_ms
    assert value.seconds == (duration_ms + 999) // 1000


@pytest.mark.parametrize("duration_ms", [0, -1, 7_200_001, 7_201_000, True, 7_200_000.0])
def test_measured_duration_refuses_over_two_hours_or_untyped_values(duration_ms) -> None:
    with pytest.raises(ConversationError, match="bounded measured source"):
        MeasuredSource(UUID(int=4), "a" * 64, duration_ms, "b" * 64)


@pytest.mark.parametrize("seconds", [1, 6000, 6001, 7200])
def test_customer_failure_receipt_round_trips_without_rewriting_old_bytes(seconds: int) -> None:
    value = receipt(seconds)
    payload = value.as_dict()
    assert CustomerTerminalFailureReceipt.from_dict(payload) == value
    assert value.fingerprint == content_hash(payload)
    validate_terminal_failure_binding(
        value, value, run_state="failed", task_state="uncertain", report_published=False
    )
    assert value.as_dict() == payload
    with pytest.raises(ValueError, match="binding mismatch"):
        validate_terminal_failure_binding(
            replace(value, reserved_seconds=2 if seconds == 1 else 1),
            value,
            run_state="failed",
            task_state="uncertain",
            report_published=False,
        )


@pytest.mark.parametrize("seconds", [0, -1, 7201, True, 7200.0])
def test_customer_failure_receipt_refuses_over_two_hours_or_untyped_values(seconds) -> None:
    with pytest.raises(ValueError, match="invalid reserved seconds"):
        receipt(seconds)
