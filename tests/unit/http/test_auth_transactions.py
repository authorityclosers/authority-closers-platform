from __future__ import annotations

from dataclasses import replace

import pytest

from ac_platform.http.auth_transactions import (
    AUTH_TRANSACTION_MAX_AGE_SECONDS,
    AuthTransaction,
    AuthTransactionCodec,
    InvalidAuthTransaction,
    normalize_return_path,
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
