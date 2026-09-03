"""Email/password identity primitives for the browser-first learner boundary.

This module deliberately keeps credentials and challenge tokens out of HTTP and
out of provider code. Password verifiers use scrypt; one-time email tokens are
stored as a hash for lookup and encrypted only so the durable worker can build
an email after the request transaction commits.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.identity.models import (
    EmailChallenge,
    EmailChallengeKind,
    PasswordCredential,
    Person,
    PersonStatus,
    Session,
)

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 256
EMAIL_MAX_LENGTH = 320
VERIFICATION_TTL = timedelta(hours=24)
RESET_TTL = timedelta(minutes=30)
PASSWORD_EMAIL_VERIFICATION_EVENT = "identity.email_verification.requested.v1"  # noqa: S105
PASSWORD_EMAIL_VERIFICATION_JOB = "email.identity_verification.v1"  # noqa: S105
PASSWORD_EMAIL_RESET_EVENT = "identity.password_reset.requested.v1"  # noqa: S105
PASSWORD_EMAIL_RESET_JOB = "email.identity_password_reset.v1"  # noqa: S105
# A fixed, non-account verifier keeps unknown-email authentication on the same
# expensive scrypt path as a known account. It is not a credential and grants
# no access; changing it would only alter the timing equalization input.
_DUMMY_PASSWORD_HASH = (
    "scrypt$ln=15,r=8,p=1$7OtOcA5tU8ZhfUFTFHv7ng$3SVUsuNLQ_44T-oYFSHTBYLsVZ1qn8JJytwPI0oQvoA"  # noqa: S105 - non-credential timing input
)


class PasswordAuthError(Exception):
    """Base error for expected password identity failures."""


class InvalidPasswordCredentials(PasswordAuthError):
    """The email/password pair or account state is not acceptable."""


class EmailVerificationRequired(PasswordAuthError):
    """The credential is valid but the email challenge is not consumed."""


class InvalidEmailChallenge(PasswordAuthError):
    """The challenge is absent, expired, consumed, or bound to another purpose."""


class PasswordPolicyError(PasswordAuthError):
    """The password does not meet the bounded credential policy."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_email(value: str) -> str:
    normalized = value.strip().lower()
    if (
        not normalized
        or len(normalized) > EMAIL_MAX_LENGTH
        or "\n" in normalized
        or "\r" in normalized
        or normalized.count("@") != 1
        or normalized.startswith("@")
    ):
        raise ValueError("email must be a single valid address")
    local, domain = normalized.rsplit("@", 1)
    if not local or not domain or "." not in domain or any(char.isspace() for char in normalized):
        raise ValueError("email must be a single valid address")
    return normalized


def validate_password(value: str) -> str:
    if not isinstance(value, str) or not PASSWORD_MIN_LENGTH <= len(value) <= PASSWORD_MAX_LENGTH:
        raise PasswordPolicyError(
            f"password must be between {PASSWORD_MIN_LENGTH} and {PASSWORD_MAX_LENGTH} characters"
        )
    if any(ord(char) < 32 for char in value):
        raise PasswordPolicyError("password contains an unsupported control character")
    return value


def hash_password(password: str) -> str:
    validate_password(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**15,
        r=8,
        p=1,
        dklen=32,
        maxmem=64 * 1024 * 1024,
    )
    return "scrypt$ln=15,r=8,p=1${}${}".format(
        base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, params, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "scrypt" or params != "ln=15,r=8,p=1":
            return False
        salt = base64.urlsafe_b64decode(salt_text + "=" * (-len(salt_text) % 4))
        expected = base64.urlsafe_b64decode(digest_text + "=" * (-len(digest_text) % 4))
        candidate = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=2**15,
            r=8,
            p=1,
            dklen=len(expected),
            maxmem=64 * 1024 * 1024,
        )
    except (ValueError, TypeError, UnicodeError, binascii.Error):
        return False
    return hmac.compare_digest(candidate, expected)


def _challenge_key(secret: bytes | str) -> bytes:
    raw = secret.encode("utf-8") if isinstance(secret, str) else secret
    if len(raw) < 32:
        raise ValueError("challenge encryption secret must contain at least 32 bytes")
    return hashlib.sha256(b"authority-closers:email-challenge:v1:" + raw).digest()


def hash_challenge_token(secret: bytes | str, token: str) -> bytes:
    raw = secret.encode("utf-8") if isinstance(secret, str) else secret
    return hmac.new(raw, b"email-challenge:" + token.encode("ascii"), hashlib.sha256).digest()


def encrypt_challenge_token(
    secret: bytes | str,
    token: str,
    *,
    kind: EmailChallengeKind,
    person_id: UUID,
) -> str:
    nonce = secrets.token_bytes(12)
    aad = f"{kind.value}:{person_id}".encode("ascii")
    ciphertext = AESGCM(_challenge_key(secret)).encrypt(nonce, token.encode("ascii"), aad)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii").rstrip("=")


def decrypt_challenge_token(
    secret: bytes | str,
    encrypted: str,
    *,
    kind: EmailChallengeKind,
    person_id: UUID,
) -> str:
    raw = base64.urlsafe_b64decode(encrypted + "=" * (-len(encrypted) % 4))
    aad = f"{kind.value}:{person_id}".encode("ascii")
    token = AESGCM(_challenge_key(secret)).decrypt(raw[:12], raw[12:], aad).decode("ascii")
    if not 40 <= len(token) <= 512:
        raise ValueError("decrypted challenge token is malformed")
    return token


@dataclass(frozen=True, slots=True)
class IssuedEmailChallenge:
    challenge_id: UUID
    person_id: UUID
    kind: EmailChallengeKind
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class PasswordRegistration:
    person_id: UUID | None
    challenge: IssuedEmailChallenge | None
    created: bool


class PasswordIdentityService:
    """Transactional password identity commands used by the HTTP adapter."""

    def __init__(self, session: AsyncSession, *, token_secret: bytes | str) -> None:
        self.session = session
        self.token_secret = token_secret

    async def register(
        self,
        *,
        email: str,
        first_name: str,
        whatsapp_number: str,
        password: str,
        consent_version: str,
        now: datetime | None = None,
    ) -> PasswordRegistration:
        email = normalize_email(email)
        validate_password(password)
        first_name = first_name.strip()
        whatsapp_number = whatsapp_number.strip()
        consent_version = consent_version.strip()
        if not 1 <= len(first_name) <= 120:
            raise ValueError("first_name must be between 1 and 120 characters")
        if not 7 <= len(whatsapp_number) <= 32:
            raise ValueError("whatsapp_number must be between 7 and 32 characters")
        if not 1 <= len(consent_version) <= 64:
            raise ValueError("consent_version must not be blank")
        current = (now or utc_now()).astimezone(UTC)
        existing = await self.session.scalar(
            select(Person).where(func.lower(Person.email) == email).with_for_update()
        )
        if existing is not None:
            # Registration intentionally has no account-existence signal.
            # Match the expensive scrypt path taken by a new registration so
            # response timing does not become the signal instead.
            hash_password(password)
            return PasswordRegistration(person_id=None, challenge=None, created=False)
        try:
            async with self.session.begin_nested():
                person = Person(
                    id=uuid4(),
                    email=email,
                    first_name=first_name,
                    display_name=first_name,
                    whatsapp_number=whatsapp_number,
                    consent_version=consent_version,
                    consented_at=current,
                    email_verified_at=None,
                )
                self.session.add(person)
                await self.session.flush()
                challenge = await self._issue_challenge(
                    person,
                    EmailChallengeKind.VERIFICATION,
                    expires_at=current + VERIFICATION_TTL,
                    now=current,
                )
                self.session.add(
                    PasswordCredential(
                        person_id=person.id,
                        password_hash=hash_password(password),
                    )
                )
                await self.session.flush()
        except IntegrityError:
            # The unique email index makes concurrent registration safe without
            # converting the race into an account-existence response. Do not
            # mask an unrelated integrity failure as a duplicate account.
            raced_person_id = await self.session.scalar(
                select(Person.id).where(func.lower(Person.email) == email)
            )
            if raced_person_id is None:
                raise
            return PasswordRegistration(person_id=None, challenge=None, created=False)
        return PasswordRegistration(person_id=person.id, challenge=challenge, created=True)

    async def authenticate(
        self,
        *,
        email: str,
        password: str,
    ) -> Person:
        normalized_email = normalize_email(email)
        row = cast(
            tuple[Person, PasswordCredential] | None,
            (
                await self.session.execute(
                    select(Person, PasswordCredential)
                    .join(PasswordCredential, PasswordCredential.person_id == Person.id)
                    .where(func.lower(Person.email) == normalized_email)
                    .with_for_update()
                )
            ).one_or_none(),
        )
        if row is None:
            verify_password(password, _DUMMY_PASSWORD_HASH)
            raise InvalidPasswordCredentials("email or password is not valid")
        person, credential = row
        password_matches = verify_password(password, credential.password_hash)
        if not password_matches or person is None or person.status != PersonStatus.ACTIVE.value:
            raise InvalidPasswordCredentials("email or password is not valid")
        if person.email_verified_at is None:
            raise EmailVerificationRequired("email verification is required")
        return person

    async def begin_reset(
        self,
        *,
        email: str,
        now: datetime | None = None,
    ) -> IssuedEmailChallenge | None:
        normalized_email = normalize_email(email)
        current = (now or utc_now()).astimezone(UTC)
        person = await self.session.scalar(
            select(Person).where(func.lower(Person.email) == normalized_email).with_for_update()
        )
        if (
            person is None
            or person.status != PersonStatus.ACTIVE.value
            or person.email_verified_at is None
        ):
            return None
        await self._consume_outstanding_challenges(
            person.id,
            EmailChallengeKind.PASSWORD_RESET,
            consumed_at=current,
        )
        return await self._issue_challenge(
            person,
            EmailChallengeKind.PASSWORD_RESET,
            expires_at=current + RESET_TTL,
            now=current,
        )

    async def begin_verification(
        self,
        *,
        email: str,
        now: datetime | None = None,
    ) -> IssuedEmailChallenge | None:
        normalized_email = normalize_email(email)
        current = (now or utc_now()).astimezone(UTC)
        person = await self.session.scalar(
            select(Person)
            .join(PasswordCredential, PasswordCredential.person_id == Person.id)
            .where(func.lower(Person.email) == normalized_email)
            .with_for_update()
        )
        if (
            person is None
            or person.status != PersonStatus.ACTIVE.value
            or person.email_verified_at is not None
        ):
            return None
        await self._consume_outstanding_challenges(
            person.id,
            EmailChallengeKind.VERIFICATION,
            consumed_at=current,
        )
        return await self._issue_challenge(
            person,
            EmailChallengeKind.VERIFICATION,
            expires_at=current + VERIFICATION_TTL,
            now=current,
        )

    async def consume_verification(
        self,
        token: str,
        *,
        now: datetime | None = None,
    ) -> Person:
        person, _challenge = await self._consume_challenge(
            token,
            EmailChallengeKind.VERIFICATION,
            now=now,
        )
        if person.email_verified_at is None:
            person.email_verified_at = (now or utc_now()).astimezone(UTC)
            person.revision += 1
        await self._consume_outstanding_challenges(
            person.id,
            EmailChallengeKind.VERIFICATION,
            consumed_at=(now or utc_now()).astimezone(UTC),
        )
        await self.session.flush()
        return person

    async def consume_reset(
        self,
        token: str,
        new_password: str,
        *,
        now: datetime | None = None,
    ) -> Person:
        validate_password(new_password)
        person, _challenge = await self._consume_challenge(
            token,
            EmailChallengeKind.PASSWORD_RESET,
            now=now,
        )
        credential = await self.session.scalar(
            select(PasswordCredential)
            .where(PasswordCredential.person_id == person.id)
            .with_for_update()
        )
        if credential is None:
            self.session.add(
                PasswordCredential(
                    person_id=person.id,
                    password_hash=hash_password(new_password),
                )
            )
        else:
            credential.password_hash = hash_password(new_password)
            credential.revision += 1
        await self._consume_outstanding_challenges(
            person.id,
            EmailChallengeKind.PASSWORD_RESET,
            consumed_at=(now or utc_now()).astimezone(UTC),
        )
        await self.session.execute(
            update(Session)
            .where(Session.person_id == person.id, Session.revoked_at.is_(None))
            .values(
                revoked_at=(now or utc_now()).astimezone(UTC),
                revocation_reason="password_reset",
                revision=Session.revision + 1,
            )
        )
        await self.session.flush()
        return person

    async def _consume_outstanding_challenges(
        self,
        person_id: UUID,
        kind: EmailChallengeKind,
        *,
        consumed_at: datetime,
    ) -> None:
        await self.session.execute(
            update(EmailChallenge)
            .where(
                EmailChallenge.person_id == person_id,
                EmailChallenge.kind == kind.value,
                EmailChallenge.consumed_at.is_(None),
            )
            .values(consumed_at=consumed_at)
        )

    async def _issue_challenge(
        self,
        person: Person,
        kind: EmailChallengeKind,
        *,
        expires_at: datetime,
        now: datetime,
    ) -> IssuedEmailChallenge:
        token = secrets.token_urlsafe(32)
        challenge = EmailChallenge(
            id=uuid4(),
            person_id=person.id,
            kind=kind.value,
            token_hash=hash_challenge_token(self.token_secret, token),
            encrypted_token=encrypt_challenge_token(
                self.token_secret,
                token,
                kind=kind,
                person_id=person.id,
            ),
            issued_at=now,
            expires_at=expires_at,
        )
        self.session.add(challenge)
        await self.session.flush()
        return IssuedEmailChallenge(
            challenge_id=challenge.id,
            person_id=person.id,
            kind=kind,
            expires_at=expires_at,
        )

    async def _consume_challenge(
        self,
        token: str,
        kind: EmailChallengeKind,
        *,
        now: datetime | None = None,
    ) -> tuple[Person, EmailChallenge]:
        if (
            not 40 <= len(token) <= 512
            or not token.isascii()
            or any(char.isspace() for char in token)
        ):
            raise InvalidEmailChallenge("the email challenge is not valid")
        current = (now or utc_now()).astimezone(UTC)
        candidate = await self.session.scalar(
            select(EmailChallenge).where(
                EmailChallenge.kind == kind.value,
                EmailChallenge.token_hash == hash_challenge_token(self.token_secret, token),
                EmailChallenge.consumed_at.is_(None),
                EmailChallenge.expires_at > current,
            )
        )
        if candidate is None:
            raise InvalidEmailChallenge("the email challenge is not valid")
        person = await self.session.scalar(
            select(Person).where(Person.id == candidate.person_id).with_for_update()
        )
        if person is None or person.status != PersonStatus.ACTIVE.value:
            raise InvalidEmailChallenge("the email challenge is not valid")
        challenge = await self.session.scalar(
            select(EmailChallenge)
            .where(
                EmailChallenge.id == candidate.id,
                EmailChallenge.person_id == person.id,
                EmailChallenge.kind == kind.value,
                EmailChallenge.token_hash == hash_challenge_token(self.token_secret, token),
                EmailChallenge.consumed_at.is_(None),
                EmailChallenge.expires_at > current,
            )
            .with_for_update()
        )
        if challenge is None:
            raise InvalidEmailChallenge("the email challenge is not valid")
        return person, challenge


__all__ = [
    "EmailVerificationRequired",
    "InvalidEmailChallenge",
    "InvalidPasswordCredentials",
    "PasswordIdentityService",
    "PasswordPolicyError",
    "PasswordRegistration",
    "PASSWORD_EMAIL_RESET_EVENT",
    "PASSWORD_EMAIL_RESET_JOB",
    "PASSWORD_EMAIL_VERIFICATION_EVENT",
    "PASSWORD_EMAIL_VERIFICATION_JOB",
    "RESET_TTL",
    "VERIFICATION_TTL",
    "decrypt_challenge_token",
    "encrypt_challenge_token",
    "hash_challenge_token",
    "hash_password",
    "normalize_email",
    "validate_password",
    "verify_password",
]
