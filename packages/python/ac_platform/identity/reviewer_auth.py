"""Dedicated reviewer mailbox authentication.

Reviewer authentication deliberately has no learner provisioning path.  A
challenge is issued only by the review HTTP composition after it has admitted a
live invitation or assignment; this module records the mailbox proof and
creates an unscoped reviewer-audience session after that proof succeeds.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.identity.models import Person, PersonStatus, ReviewerAuthChallenge, SessionAudience
from ac_platform.identity.services import (
    InvalidSessionTokenError,
    IssuedSession,
    PersonSnapshot,
    SessionMetadata,
    normalize_email,
)

REVIEWER_AUTH_CHALLENGE_TTL = timedelta(minutes=15)
REVIEWER_AUTH_CHALLENGE_COOLDOWN = timedelta(minutes=1)
REVIEWER_AUTH_BROWSER_NONCE_MIN_BYTES = 32
REVIEWER_AUTH_EVENT = "identity.reviewer_auth.requested.v1"
REVIEWER_AUTH_JOB = "email.identity_reviewer_auth.v1"
REVIEWER_AUTH_PATH = "/reviewer/verify"


class ReviewerAuthenticationError(Exception):
    """Base error for expected reviewer authentication failures."""


class InvalidReviewerChallenge(ReviewerAuthenticationError):
    """The reviewer mailbox challenge is absent, expired, consumed, or malformed."""


class ReviewerAccountUnavailable(ReviewerAuthenticationError):
    """The canonical person cannot hold a reviewer session."""


@dataclass(frozen=True, slots=True)
class IssuedReviewerChallenge:
    """Safe challenge metadata for the caller-owned outbox transaction."""

    challenge_id: UUID
    email: str
    person_id: UUID | None
    invitation_id: UUID | None
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ReviewerAuthentication:
    """Canonical person and one-time reviewer session after mailbox proof."""

    person: PersonSnapshot
    session: IssuedSession
    invitation_id: UUID | None


@dataclass(frozen=True, slots=True)
class ReviewerSession:
    """Resolved reviewer session; tenant scope is intentionally absent."""

    person: PersonSnapshot
    session: SessionMetadata


def _secret_bytes(secret: bytes | str) -> bytes:
    raw = secret.encode("utf-8") if isinstance(secret, str) else secret
    if len(raw) < 32:
        raise ValueError("reviewer challenge secret must contain at least 32 bytes")
    return raw


def _encryption_key(secret: bytes | str) -> bytes:
    return hashlib.sha256(
        b"authority-closers:reviewer-auth-challenge:v1:" + _secret_bytes(secret)
    ).digest()


def hash_reviewer_challenge_token(secret: bytes | str, token: str) -> bytes:
    """Return the lookup digest for one reviewer challenge bearer."""

    return hmac.new(
        _secret_bytes(secret),
        b"reviewer-auth-challenge:" + token.encode("ascii"),
        hashlib.sha256,
    ).digest()


def validate_reviewer_browser_nonce(browser_nonce: str) -> str:
    """Validate the canonical URL-safe encoding of a browser nonce.

    The HTTP boundary generates this value with ``secrets.token_urlsafe(32)``
    and keeps it in a host-only cookie. Identity accepts only the unpadded
    canonical encoding, so alternate encodings cannot represent the same
    nonce at this boundary.
    """

    allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
    if (
        not isinstance(browser_nonce, str)
        or not 43 <= len(browser_nonce) <= 512
        or any(character not in allowed for character in browser_nonce)
    ):
        raise InvalidReviewerChallenge("the reviewer browser binding is invalid")
    try:
        raw = base64.urlsafe_b64decode(browser_nonce + "=" * (-len(browser_nonce) % 4))
    except (binascii.Error, ValueError, TypeError) as exc:
        raise InvalidReviewerChallenge("the reviewer browser binding is invalid") from exc
    if (
        len(raw) < REVIEWER_AUTH_BROWSER_NONCE_MIN_BYTES
        or base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=") != browser_nonce
    ):
        raise InvalidReviewerChallenge("the reviewer browser binding is invalid")
    return browser_nonce


def hash_reviewer_browser_nonce(secret: bytes | str, browser_nonce: str) -> bytes:
    """Hash a validated browser nonce with a reviewer-specific HMAC domain."""

    validated = validate_reviewer_browser_nonce(browser_nonce)
    return hmac.new(
        _secret_bytes(secret),
        b"reviewer-auth-browser-nonce:" + validated.encode("ascii"),
        hashlib.sha256,
    ).digest()


def encrypt_reviewer_challenge_token(
    secret: bytes | str,
    token: str,
    challenge_id: UUID,
) -> str:
    """Encrypt a delivery-only token using the challenge identifier as AAD."""

    nonce = secrets.token_bytes(12)
    aad = f"reviewer-auth-challenge:v1:{challenge_id}".encode("ascii")
    ciphertext = AESGCM(_encryption_key(secret)).encrypt(
        nonce,
        token.encode("ascii"),
        aad,
    )
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii").rstrip("=")


def decrypt_reviewer_challenge_token(
    secret: bytes | str,
    encrypted: str,
    challenge_id: UUID,
) -> str:
    """Decrypt a token only at the transactional email delivery boundary."""

    try:
        raw = base64.urlsafe_b64decode(encrypted + "=" * (-len(encrypted) % 4))
        aad = f"reviewer-auth-challenge:v1:{challenge_id}".encode("ascii")
        token = AESGCM(_encryption_key(secret)).decrypt(raw[:12], raw[12:], aad).decode("ascii")
    except (InvalidTag, ValueError, TypeError, UnicodeError) as exc:
        raise InvalidReviewerChallenge("the reviewer challenge payload is invalid") from exc
    if not 40 <= len(token) <= 512 or any(char.isspace() for char in token):
        raise InvalidReviewerChallenge("the reviewer challenge payload is invalid")
    return token


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _now(value: datetime | None) -> datetime:
    return _as_utc(value or datetime.now(UTC))


def _person_snapshot(person: Person) -> PersonSnapshot:
    return PersonSnapshot(
        id=person.id,
        email=person.email,
        display_name=person.display_name,
        status=person.status,
        email_verified_at=(
            None if person.email_verified_at is None else _as_utc(person.email_verified_at)
        ),
        consent_version=person.consent_version,
        consented_at=None if person.consented_at is None else _as_utc(person.consented_at),
        revision=person.revision,
    )


def _cooldown_key(email: str) -> int:
    # pg_advisory_xact_lock accepts a signed 32-bit integer key.  The digest is
    # domain-separated so this lock cannot collide intentionally with unrelated
    # identity commands.
    digest = hashlib.sha256(f"reviewer-auth:{email}".encode()).digest()
    return int.from_bytes(digest[:4], byteorder="big", signed=True)


class ReviewerAuthenticationService:
    """Issue and consume dedicated reviewer mailbox challenges."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        challenge_secret: bytes | str,
        token_pepper: bytes | str,
        session_ttl: timedelta = timedelta(days=30),
    ) -> None:
        self.session = session
        self.challenge_secret = _secret_bytes(challenge_secret)
        self.token_pepper = _secret_bytes(token_pepper)
        if session_ttl <= timedelta(0):
            raise ValueError("reviewer session ttl must be positive")
        self.session_ttl = session_ttl

    async def _lock_email(self, email: str) -> None:
        bind = self.session.get_bind()
        if bind.dialect.name == "postgresql":
            await self.session.execute(
                select(func.pg_advisory_xact_lock(739003, _cooldown_key(email)))
            )

    async def issue_challenge(
        self,
        *,
        email: str,
        browser_nonce: str,
        invitation_id: UUID | None = None,
        person_id: UUID | None = None,
        now: datetime | None = None,
    ) -> IssuedReviewerChallenge | None:
        """Create one challenge, or ``None`` during the per-email cooldown.

        The caller must first establish a live invitation or assignment.  This
        service intentionally has no review-domain import and cannot be used as
        an access lookup by itself.
        """

        normalized_email = normalize_email(email)
        browser_nonce_hash = hash_reviewer_browser_nonce(self.challenge_secret, browser_nonce)
        current = _now(now)
        await self._lock_email(normalized_email)
        recent = await self.session.scalar(
            select(ReviewerAuthChallenge)
            .where(
                func.lower(ReviewerAuthChallenge.email) == func.lower(normalized_email),
                ReviewerAuthChallenge.consumed_at.is_(None),
                ReviewerAuthChallenge.issued_at >= current - REVIEWER_AUTH_CHALLENGE_COOLDOWN,
            )
            .order_by(desc(ReviewerAuthChallenge.issued_at))
            .with_for_update()
        )
        if recent is not None:
            return None
        person = await self.session.scalar(
            select(Person)
            .where(func.lower(Person.email) == func.lower(normalized_email))
            .with_for_update()
        )
        if person_id is not None and (person is None or person.id != person_id):
            raise ReviewerAccountUnavailable("the reviewer identity binding is unavailable")
        if person is not None and person.status != PersonStatus.ACTIVE.value:
            raise ReviewerAccountUnavailable("the reviewer identity is unavailable")
        challenge_id = uuid4()
        token = secrets.token_urlsafe(48)
        challenge = ReviewerAuthChallenge(
            id=challenge_id,
            person_id=None if person is None else person.id,
            invitation_id=invitation_id,
            email=normalized_email,
            token_hash=hash_reviewer_challenge_token(self.challenge_secret, token),
            browser_nonce_hash=browser_nonce_hash,
            encrypted_token=encrypt_reviewer_challenge_token(
                self.challenge_secret,
                token,
                challenge_id,
            ),
            issued_at=current,
            expires_at=current + REVIEWER_AUTH_CHALLENGE_TTL,
        )
        self.session.add(challenge)
        await self.session.flush()
        return IssuedReviewerChallenge(
            challenge_id=challenge.id,
            email=normalized_email,
            person_id=challenge.person_id,
            invitation_id=challenge.invitation_id,
            expires_at=challenge.expires_at,
        )

    async def consume_challenge(
        self,
        token: str,
        *,
        browser_nonce: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
        now: datetime | None = None,
    ) -> ReviewerAuthentication:
        """Consume mailbox proof and issue a reviewer-audience session."""

        if (
            not isinstance(token, str)
            or not 40 <= len(token) <= 512
            or not token.isascii()
            or any(char.isspace() for char in token)
        ):
            raise InvalidReviewerChallenge("the reviewer challenge is not valid")
        browser_nonce_hash = hash_reviewer_browser_nonce(self.challenge_secret, browser_nonce)
        current = _now(now)
        challenge = await self.session.scalar(
            select(ReviewerAuthChallenge)
            .where(
                ReviewerAuthChallenge.token_hash
                == hash_reviewer_challenge_token(self.challenge_secret, token),
                ReviewerAuthChallenge.consumed_at.is_(None),
                ReviewerAuthChallenge.expires_at > current,
            )
            .with_for_update()
        )
        if challenge is None:
            raise InvalidReviewerChallenge("the reviewer challenge is not valid")
        if not hmac.compare_digest(bytes(challenge.browser_nonce_hash), browser_nonce_hash):
            raise InvalidReviewerChallenge("the reviewer challenge is not valid")
        person = await self._resolve_person(challenge, current)
        challenge.consumed_at = current
        challenge.person_id = person.id
        await self.session.flush()
        identity = AsyncIdentityApplication(
            self.session,
            token_pepper=self.token_pepper,
            session_ttl=self.session_ttl,
        )
        issued = await identity.issue_reviewer_session(
            person.id,
            user_agent=user_agent,
            ip_address=ip_address,
            now=current,
        )
        return ReviewerAuthentication(
            person=_person_snapshot(person),
            session=issued,
            invitation_id=challenge.invitation_id,
        )

    async def _resolve_person(
        self,
        challenge: ReviewerAuthChallenge,
        current: datetime,
    ) -> Person:
        if challenge.person_id is None:
            person = await self.session.scalar(
                select(Person)
                .where(func.lower(Person.email) == func.lower(challenge.email))
                .with_for_update()
            )
            if person is None:
                person = Person(
                    id=uuid4(),
                    email=challenge.email,
                    email_verified_at=current,
                )
                try:
                    async with self.session.begin_nested():
                        self.session.add(person)
                        await self.session.flush()
                except IntegrityError:
                    person = await self.session.scalar(
                        select(Person)
                        .where(func.lower(Person.email) == func.lower(challenge.email))
                        .with_for_update()
                    )
                    if person is None:
                        raise ReviewerAccountUnavailable(
                            "the reviewer identity race did not produce a canonical person"
                        ) from None
        else:
            person = await self.session.scalar(
                select(Person).where(Person.id == challenge.person_id).with_for_update()
            )
        if person is None or person.status != PersonStatus.ACTIVE.value or person.email is None:
            raise InvalidReviewerChallenge("the reviewer challenge is not valid")
        try:
            person_email = normalize_email(person.email)
        except ValueError:
            raise InvalidReviewerChallenge("the reviewer challenge is not valid") from None
        if not hmac.compare_digest(
            person_email.casefold().encode("utf-8"),
            challenge.email.casefold().encode("utf-8"),
        ):
            raise InvalidReviewerChallenge("the reviewer challenge is not valid")
        if person.email_verified_at is None:
            person.email_verified_at = current
            person.revision += 1
        return person

    async def resolve_session(
        self,
        token: str,
        *,
        now: datetime | None = None,
    ) -> ReviewerSession:
        """Resolve only a reviewer-audience session; no tenant is selected."""

        identity = AsyncIdentityApplication(
            self.session,
            token_pepper=self.token_pepper,
            session_ttl=self.session_ttl,
        )
        try:
            resolved = await identity.resolve_actor(
                token,
                expected_audience=SessionAudience.REVIEWER,
                now=now,
            )
        except InvalidSessionTokenError:
            raise
        person = await identity.repository.get_person(resolved.actor.person_id)
        stored = await identity.repository.get_session(resolved.actor.session_id)
        if person is None or stored is None:
            raise InvalidReviewerChallenge("the reviewer session person is unavailable")
        return ReviewerSession(person=person, session=identity._metadata(stored))

    async def revoke_session(
        self,
        token: str,
        *,
        reason: str = "reviewer_logout",
        now: datetime | None = None,
    ) -> SessionMetadata:
        """Revoke only the reviewer session represented by ``token``."""

        identity = AsyncIdentityApplication(
            self.session,
            token_pepper=self.token_pepper,
            session_ttl=self.session_ttl,
        )
        resolved = await identity.resolve_actor(
            token,
            expected_audience=SessionAudience.REVIEWER,
            now=now,
        )
        return await identity.revoke_self(
            token,
            resolved.actor.session_id,
            expected_audience=SessionAudience.REVIEWER,
            reason=reason,
            now=now,
        )


__all__ = [
    "IssuedReviewerChallenge",
    "InvalidReviewerChallenge",
    "REVIEWER_AUTH_CHALLENGE_COOLDOWN",
    "REVIEWER_AUTH_BROWSER_NONCE_MIN_BYTES",
    "REVIEWER_AUTH_CHALLENGE_TTL",
    "REVIEWER_AUTH_EVENT",
    "REVIEWER_AUTH_JOB",
    "REVIEWER_AUTH_PATH",
    "ReviewerAuthentication",
    "ReviewerAuthenticationError",
    "ReviewerAuthenticationService",
    "ReviewerAccountUnavailable",
    "ReviewerSession",
    "decrypt_reviewer_challenge_token",
    "encrypt_reviewer_challenge_token",
    "hash_reviewer_browser_nonce",
    "hash_reviewer_challenge_token",
    "validate_reviewer_browser_nonce",
]
