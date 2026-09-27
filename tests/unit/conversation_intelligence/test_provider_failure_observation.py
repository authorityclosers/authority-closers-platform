"""Strict shape and bound tests for provider failure observations."""

from __future__ import annotations

import hashlib

import pytest

from ac_platform.conversation_intelligence.provider_failure_observation import (
    MAX_ERROR_RESPONSE_BODY_BYTES,
    MAX_RETRY_AFTER_SECONDS,
    PROVIDER_FAILURE_OBSERVATION_SCHEMA,
    ProviderFailureObservation,
)


def _observation(**changes: object) -> ProviderFailureObservation:
    values: dict[str, object] = {
        "reservation_id": "reservation-1",
        "attempt_id": "attempt-1",
        "quote_fingerprint": "a" * 64,
        "provider": "gemini",
        "model": "gemini-2.5-flash",
        "operation": "extract_context_evidence",
        "input_sha256": "b" * 64,
        "http_status": 503,
        "response_body_complete": True,
        "response_body_observed_bytes": 0,
        "response_body_sha256": hashlib.sha256(b"").hexdigest(),
        "provider_request_id_sha256": hashlib.sha256(b"opaque-id").hexdigest(),
        "retry_after_seconds": 0,
        "diagnostic_category": None,
    }
    values.update(changes)
    return ProviderFailureObservation(**values)  # type: ignore[arg-type]


def test_observation_round_trips_exact_schema_without_remote_identifier() -> None:
    observation = _observation()
    encoded = observation.as_dict()

    assert encoded["schema"] == PROVIDER_FAILURE_OBSERVATION_SCHEMA
    assert "provider_request_id" not in encoded
    assert encoded["provider_request_id_sha256"] == hashlib.sha256(b"opaque-id").hexdigest()
    assert ProviderFailureObservation.from_dict(encoded) == observation


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("http_status", True),
        ("http_status", 200),
        ("http_status", 600),
        ("response_body_complete", 1),
        ("response_body_observed_bytes", True),
        ("response_body_observed_bytes", MAX_ERROR_RESPONSE_BODY_BYTES + 1),
        ("response_body_sha256", None),
        ("provider_request_id_sha256", "sk_live_synthetic_secret"),
        ("retry_after_seconds", MAX_RETRY_AFTER_SECONDS + 1),
    ],
)
def test_observation_rejects_invalid_types_and_bounds(field: str, value: object) -> None:
    with pytest.raises(ValueError, match="invalid provider failure observation"):
        _observation(**{field: value})


def test_incomplete_body_cannot_claim_a_digest() -> None:
    observation = _observation(
        response_body_complete=False,
        response_body_observed_bytes=MAX_ERROR_RESPONSE_BODY_BYTES,
        response_body_sha256=None,
    )
    assert ProviderFailureObservation.from_dict(observation.as_dict()) == observation

    with pytest.raises(ValueError, match="invalid provider failure observation"):
        _observation(response_body_complete=False, response_body_sha256="c" * 64)


def test_decoder_rejects_schema_drift_and_extra_fields() -> None:
    encoded = _observation().as_dict()
    encoded["schema"] = "ac.sales_xray.provider_failure_observation/2"
    with pytest.raises(ValueError, match="invalid provider failure observation"):
        ProviderFailureObservation.from_dict(encoded)

    encoded = _observation().as_dict()
    encoded["remote_message"] = "must not pass"
    with pytest.raises(ValueError, match="invalid provider failure observation"):
        ProviderFailureObservation.from_dict(encoded)
