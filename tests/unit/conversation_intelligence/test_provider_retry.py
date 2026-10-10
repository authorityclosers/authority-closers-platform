"""Refusal eligibility never grants another send or clears financial evidence."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from ac_platform.conversation_intelligence.entitlements import Reservation
from ac_platform.conversation_intelligence.provider_retry import assess_provider_retry
from tests.unit.conversation_intelligence.test_entitlements import permission, quote
from tests.unit.conversation_intelligence.test_provider_failure_observation import _observation

NOW = datetime.fromtimestamp(200, UTC)


def bound_observation(**changes):
    value = quote(expires_at_epoch=10_000)
    reserved = Reservation(
        "reservation-1",
        value,
        permission(value, expires_at_epoch=9_000),
        state="in_flight",
        attempt_id="attempt-1",
    )
    observed = _observation(
        quote_fingerprint=value.fingerprint,
        provider=value.provider_id,
        model=value.provider_model,
        operation=value.operation,
        input_sha256=value.input_sha256,
        **changes,
    )
    return observed, reserved


def assess(observed, reserved, **changes):
    return assess_provider_retry(
        observed,
        reserved,
        **{"observed_at": NOW, "claim_count": 1, "claim_limit": 3, **changes},
    )


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_complete_empty_transient_response_is_eligible_but_not_authorized(status):
    observed, reserved = bound_observation(http_status=status)
    result = assess(observed, reserved)
    assert result.state == "transport_retry_eligible"
    assert NOW + timedelta(seconds=5) <= result.not_before <= NOW + timedelta(seconds=6.25)
    assert result.as_dict()["dispatch_authorized"] is False
    assert result.as_dict()["provider_charge_state"] == "unresolved"
    assert reserved.state == "in_flight" and reserved.no_charge_receipt is None


@pytest.mark.parametrize("status", [400, 401, 403, 404, 408, 409, 422, 501])
def test_other_statuses_do_not_invent_retry_eligibility(status):
    observed, reserved = bound_observation(http_status=status)
    result = assess(observed, reserved)
    assert result.state == "non_retryable" and result.not_before is None


@pytest.mark.parametrize(
    "changes",
    [
        {"response_body_complete": False, "response_body_sha256": None},
        {"response_body_observed_bytes": 1, "response_body_sha256": "c" * 64},
        {"response_body_sha256": "c" * 64},
    ],
)
def test_truncated_nonempty_and_inconsistent_empty_responses_need_reconciliation(changes):
    observed, reserved = bound_observation(**changes)
    result = assess(observed, reserved)
    assert result.state == "reconciliation_required" and result.not_before is None


@pytest.mark.parametrize(
    "field",
    [
        "reservation_id",
        "attempt_id",
        "quote_fingerprint",
        "provider",
        "model",
        "operation",
        "input_sha256",
    ],
)
def test_observation_must_bind_to_the_exact_original_attempt(field):
    observed, reserved = bound_observation()
    wrong = "c" * 64 if field in {"quote_fingerprint", "input_sha256"} else "other-attempt"
    with pytest.raises(ValueError, match="binding mismatch"):
        assess(replace(observed, **{field: wrong}), reserved)


def test_retry_after_is_a_minimum_and_never_truncated_by_local_backoff_cap():
    observed, reserved = bound_observation(retry_after_seconds=3600)
    result = assess(observed, reserved)
    assert result.not_before == NOW + timedelta(seconds=3600)
    assert result == assess(observed, reserved)
    other, _ = bound_observation(attempt_id="other-attempt")
    other_reserved = replace(reserved, attempt_id="other-attempt")
    zero, _ = bound_observation(retry_after_seconds=0)
    assert assess(zero, reserved).not_before != assess(other, other_reserved).not_before
    assert assess(zero, reserved, claim_count=2).not_before > assess(zero, reserved).not_before


@pytest.mark.parametrize("count", [1, 3, 25])
def test_exhaustion_never_resets_the_claim_counter(count):
    observed, reserved = bound_observation()
    result = assess(observed, reserved, claim_count=count, claim_limit=count)
    assert result.state == "claim_limit_exhausted" and result.not_before is None


@pytest.mark.parametrize("boundary", ["quote", "permission"])
def test_server_wait_must_fit_both_original_authorization_windows(boundary):
    observed, reserved = bound_observation(retry_after_seconds=3600)
    if boundary == "quote":
        value = replace(reserved.quote, expires_at_epoch=3800)
        reserved = replace(
            reserved, quote=value, permission=permission(value, expires_at_epoch=9000)
        )
        observed = replace(observed, quote_fingerprint=value.fingerprint)
    else:
        reserved = replace(reserved, permission=replace(reserved.permission, expires_at_epoch=3800))
    result = assess(observed, reserved)
    assert result.state == "authorization_window_exhausted" and result.not_before is None


def test_diagnostic_category_is_not_treated_as_a_transient_refusal():
    observed, reserved = bound_observation(diagnostic_category="key_invalid")
    assert assess(observed, reserved).state == "non_retryable"


@pytest.mark.parametrize(
    "changes",
    [
        {"claim_count": True},
        {"claim_limit": True},
        {"claim_count": 0},
        {"claim_count": 4},
        {"claim_limit": 26},
        {"claim_limit": 0},
        {"observed_at": NOW.replace(tzinfo=None)},
    ],
)
def test_invalid_bounds_and_naive_time_are_rejected(changes):
    observed, reserved = bound_observation()
    with pytest.raises(ValueError, match="assessment bounds"):
        assess(observed, reserved, **changes)


def test_no_dispatch_or_predating_observation_cannot_certify_retry():
    observed, reserved = bound_observation()
    with pytest.raises(ValueError, match="binding mismatch"):
        assess(observed, replace(reserved, state="reserved", attempt_id=None))
    with pytest.raises(ValueError, match="binding mismatch"):
        assess(observed, reserved, observed_at=datetime.fromtimestamp(99, UTC))
