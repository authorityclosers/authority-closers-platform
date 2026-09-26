from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import replace
from uuid import UUID

import pytest

from ac_platform.http.auth_transactions import (
    AUTH_TRANSACTION_MAX_AGE_SECONDS,
    SALES_XRAY_COMPLETION_RECEIPT_TTL_SECONDS,
    AuthTransaction,
    AuthTransactionCodec,
    InvalidAuthTransaction,
    SalesXrayCompletionReceiptCodec,
    normalize_return_path,
    sales_xray_completion_flow_id,
)
from ac_platform.identity.services import ProviderAuthorizationType

SECRET = "auth-transaction-test-secret-that-is-long-enough"  # noqa: S105
NOW = 1_788_055_200
KEY = "unit-auth-transaction-signing-key-is-long-enough"  # noqa: S105


def _transaction() -> AuthTransaction:
    return AuthTransaction.issue(
        ProviderAuthorizationType.AUTHENTICATE,
        surface="learner",
        return_path="/home?from=login",
        now=NOW,
    )


def test_signed_transaction_round_trips_all_server_owned_callback_state() -> None:
    transaction = _transaction()

    decoded = AuthTransactionCodec(SECRET).decode(
        AuthTransactionCodec(SECRET).encode(transaction),
        now=NOW + 1,
    )

    assert decoded == transaction
    assert len(decoded.state) >= 32
    assert len(decoded.nonce) >= 32
    assert len(decoded.pkce_verifier) >= 43
    assert len(decoded.pkce_challenge) == 43


def test_transaction_tampering_is_rejected_before_callback_exchange() -> None:
    codec = AuthTransactionCodec(SECRET)
    encoded = codec.encode(_transaction())
    payload, signature = encoded.split(".")
    replacement = "A" if payload[-1] != "A" else "B"

    with pytest.raises(InvalidAuthTransaction, match="signature"):
        codec.decode(f"{payload[:-1]}{replacement}.{signature}", now=NOW)


@pytest.mark.parametrize(
    "current_time",
    [
        NOW + AUTH_TRANSACTION_MAX_AGE_SECONDS + 1,
        NOW - 31,
    ],
)
def test_expired_or_future_dated_transaction_is_rejected(current_time: int) -> None:
    codec = AuthTransactionCodec(SECRET)

    with pytest.raises(InvalidAuthTransaction):
        codec.decode(codec.encode(_transaction()), now=current_time)


@pytest.mark.parametrize(
    "candidate",
    [
        "https://evil.example/steal",
        "//evil.example/steal",
        "/\\evil.example/steal",
        "/home#fragment",
        "home",
    ],
)
def test_external_or_ambiguous_return_paths_are_rejected(candidate: str) -> None:
    with pytest.raises(InvalidAuthTransaction):
        normalize_return_path(candidate)


def test_payload_cannot_be_relabelled_to_another_authorization_intent() -> None:
    codec = AuthTransactionCodec(SECRET)
    transaction = replace(
        _transaction(),
        authorization_type=ProviderAuthorizationType.LINK,
    )

    decoded = codec.decode(codec.encode(transaction), now=NOW)

    assert decoded.authorization_type is ProviderAuthorizationType.LINK


def test_short_signing_secret_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least 32 bytes"):
        AuthTransactionCodec("too-short")


def test_signed_oauth_transaction_round_trips_exact_learner_consent_version() -> None:
    transaction = AuthTransaction.issue(
        ProviderAuthorizationType.REGISTER,
        surface="learner",
        return_path="/home",
        consent_version="staging-test-document-v1",
        now=1_780_000_000,
    )

    decoded = AuthTransactionCodec(KEY).decode(
        AuthTransactionCodec(KEY).encode(transaction),
        now=1_780_000_001,
    )

    assert decoded == transaction
    assert decoded.consent_version == "staging-test-document-v1"


def test_signed_oauth_transaction_cannot_change_consent_without_a_new_signature() -> None:
    codec = AuthTransactionCodec(KEY)
    transaction = AuthTransaction.issue(
        ProviderAuthorizationType.REGISTER,
        surface="learner",
        return_path="/home",
        consent_version="staging-test-document-v1",
        now=1_780_000_000,
    )
    encoded = codec.encode(transaction)
    forged = codec.encode(replace(transaction, consent_version="forged-v1"))
    assert encoded != forged
    forged_payload, forged_signature = forged.rsplit(".", maxsplit=1)
    tampered = (
        f"{forged_payload}.{'A' if forged_signature[0] != 'A' else 'B'}{forged_signature[1:]}"
    )

    with pytest.raises(InvalidAuthTransaction):
        codec.decode(tampered, now=1_780_000_001)


def test_signed_oauth_transaction_rejects_invalid_consent_version() -> None:
    with pytest.raises(InvalidAuthTransaction):
        AuthTransaction.issue(
            ProviderAuthorizationType.REGISTER,
            surface="learner",
            return_path="/home",
            consent_version=" ",
        )


def test_signed_age_attestation_is_bound_to_current_consent() -> None:
    transaction = AuthTransaction.issue(
        ProviderAuthorizationType.REGISTER,
        surface="sales_xray",
        return_path="/",
        consent_version="current-document-v2",
        age_attested=True,
        now=NOW,
    )
    codec = AuthTransactionCodec(KEY)

    decoded = codec.decode(codec.encode(transaction), now=NOW)

    assert decoded == transaction
    assert decoded.age_attested is True
    with pytest.raises(InvalidAuthTransaction, match="consent version"):
        AuthTransaction.issue(
            ProviderAuthorizationType.REGISTER,
            surface="sales_xray",
            return_path="/",
            age_attested=True,
            now=NOW,
        )


def test_legacy_signed_transaction_without_age_field_defaults_to_false() -> None:
    codec = AuthTransactionCodec(KEY)
    transaction = _transaction()
    encoded = codec.encode(transaction)
    encoded_payload, _signature = encoded.split(".")
    raw = base64.urlsafe_b64decode(encoded_payload + "=" * (-len(encoded_payload) % 4))
    payload = json.loads(raw)
    payload.pop("age_attested")
    legacy_payload = (
        base64.urlsafe_b64encode(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        .rstrip(b"=")
        .decode("ascii")
    )
    legacy_signature = (
        base64.urlsafe_b64encode(
            hmac.new(KEY.encode("utf-8"), legacy_payload.encode("ascii"), hashlib.sha256).digest()
        )
        .rstrip(b"=")
        .decode("ascii")
    )

    decoded = codec.decode(f"{legacy_payload}.{legacy_signature}", now=NOW)

    assert decoded.age_attested is False


def test_sales_xray_completion_receipt_round_trips_flow_and_session_binding() -> None:
    codec = SalesXrayCompletionReceiptCodec(KEY)
    flow_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    session_id = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")

    receipt = codec.decode(
        codec.encode(flow_id=flow_id, session_id=session_id, now=NOW), now=NOW + 1
    )

    assert receipt.flow_id == flow_id
    assert receipt.session_id == session_id
    assert receipt.surface == "sales_xray"
    assert receipt.issued_at == NOW
    assert receipt.expires_at == NOW + SALES_XRAY_COMPLETION_RECEIPT_TTL_SECONDS


def test_sales_xray_completion_receipt_rejects_tampering_expiry_and_wrong_key() -> None:
    codec = SalesXrayCompletionReceiptCodec(KEY)
    encoded = codec.encode(
        flow_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        session_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        now=NOW,
    )
    payload, signature = encoded.split(".")

    with pytest.raises(InvalidAuthTransaction, match="signature"):
        codec.decode(f"{payload}.{('A' if signature[0] != 'A' else 'B')}{signature[1:]}", now=NOW)
    with pytest.raises(InvalidAuthTransaction, match="expired"):
        codec.decode(encoded, now=NOW + SALES_XRAY_COMPLETION_RECEIPT_TTL_SECONDS)
    with pytest.raises(InvalidAuthTransaction, match="signature"):
        SalesXrayCompletionReceiptCodec(SECRET).decode(encoded, now=NOW)


@pytest.mark.parametrize(
    "return_path",
    [
        "/auth/complete?flow=aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "/auth/complete?flow=AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
    ],
)
def test_sales_xray_completion_flow_accepts_only_a_canonical_uuid(return_path: str) -> None:
    assert sales_xray_completion_flow_id(return_path) == UUID(
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    )


@pytest.mark.parametrize(
    "return_path",
    [
        "/auth/complete",
        "/auth/complete?flow=not-a-uuid",
        "/auth/complete?flow=aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa&next=/home",
        "/auth/complete?flow=aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa&flow=bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "/home?flow=aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    ],
)
def test_sales_xray_completion_flow_rejects_missing_or_ambiguous_flow(return_path: str) -> None:
    assert sales_xray_completion_flow_id(return_path) is None
