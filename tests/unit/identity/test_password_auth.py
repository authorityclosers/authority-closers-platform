from __future__ import annotations

from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from cryptography.exceptions import InvalidTag

from ac_platform.identity.models import EmailChallengeKind, Person
from ac_platform.identity.password_auth import (
    InvalidPasswordCredentials,
    PasswordIdentityService,
    PasswordPolicyError,
    decrypt_challenge_token,
    encrypt_challenge_token,
    hash_challenge_token,
    hash_password,
    normalize_email,
    validate_password,
    verify_password,
)

TOKEN_SECRET = b"password-auth-unit-test-secret-value-32-bytes"


def test_password_hash_is_salted_and_never_contains_plaintext() -> None:
    password = "a long passphrase for the learner"  # noqa: S105

    first = hash_password(password)
    second = hash_password(password)

    assert first.startswith("scrypt$ln=15,r=8,p=1$")
    assert first != second
    assert password not in first
    assert verify_password(password, first)
    assert not verify_password("not the password", first)
    assert not verify_password(password, "malformed")


@pytest.mark.parametrize(
    "password",
    [
        "short",
        "x" * 257,
        "valid-length\nwith-control",
    ],
)
def test_password_policy_rejects_out_of_bounds_or_control_characters(password: str) -> None:
    with pytest.raises(PasswordPolicyError):
        validate_password(password)


def test_email_normalization_is_bounded_and_case_insensitive() -> None:
    assert normalize_email("  Learner@Example.COM  ") == "learner@example.com"
    for invalid in (
        "missing-at.example.com",
        "@example.com",
        "person@localhost",
        "a\nb@example.com",
    ):
        with pytest.raises(ValueError, match="email"):
            normalize_email(invalid)


def test_email_challenge_is_encrypted_and_bound_to_person_and_purpose() -> None:
    person_id = uuid4()
    other_person_id = uuid4()
    token = "t" * 43

    encrypted = encrypt_challenge_token(
        TOKEN_SECRET,
        token,
        kind=EmailChallengeKind.VERIFICATION,
        person_id=person_id,
    )

    assert token not in encrypted
    assert (
        decrypt_challenge_token(
            TOKEN_SECRET,
            encrypted,
            kind=EmailChallengeKind.VERIFICATION,
            person_id=person_id,
        )
        == token
    )
    with pytest.raises(InvalidTag):
        decrypt_challenge_token(
            TOKEN_SECRET,
            encrypted,
            kind=EmailChallengeKind.PASSWORD_RESET,
            person_id=person_id,
        )
    with pytest.raises(InvalidTag):
        decrypt_challenge_token(
            TOKEN_SECRET,
            encrypted,
            kind=EmailChallengeKind.VERIFICATION,
            person_id=other_person_id,
        )


def test_challenge_lookup_hash_is_keyed_and_does_not_expose_token() -> None:
    token = "x" * 43
    first = hash_challenge_token(TOKEN_SECRET, token)
    second = hash_challenge_token(TOKEN_SECRET, token)

    assert first == second
    assert len(first) == 32
    assert token.encode() not in first
    assert hash_challenge_token(TOKEN_SECRET, "y" * 43) != first


async def test_unknown_email_still_runs_one_scrypt_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = AsyncMock()
    database.execute.return_value = Mock(one_or_none=Mock(return_value=None))
    calls: list[tuple[str, str]] = []

    def record_verification(password: str, encoded: str) -> bool:
        calls.append((password, encoded))
        return False

    monkeypatch.setattr(
        "ac_platform.identity.password_auth.verify_password",
        record_verification,
    )

    with pytest.raises(InvalidPasswordCredentials):
        await PasswordIdentityService(database, token_secret=TOKEN_SECRET).authenticate(
            email="missing@example.com",
            password="a submitted password",  # noqa: S106
        )

    assert len(calls) == 1
    assert calls[0][0] == "a submitted password"
    assert calls[0][1].startswith("scrypt$ln=15,r=8,p=1$")


async def test_existing_registration_still_runs_one_scrypt_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = AsyncMock()
    database.scalar.return_value = Person(id=uuid4(), email="learner@example.com")
    calls: list[str] = []

    def record_hash(password: str) -> str:
        calls.append(password)
        return "discarded"

    monkeypatch.setattr("ac_platform.identity.password_auth.hash_password", record_hash)

    result = await PasswordIdentityService(database, token_secret=TOKEN_SECRET).register(
        email="learner@example.com",
        first_name="Learner",
        whatsapp_number="+12025550123",
        password="a submitted password",  # noqa: S106
        consent_version="test-consent-v1",
    )

    assert result.created is False
    assert result.person_id is None
    assert result.challenge is None
    assert calls == ["a submitted password"]
