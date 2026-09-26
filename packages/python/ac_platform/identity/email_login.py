"""Single-purpose email-code sign-in and post-verification provisioning."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.service import AuditRepository
from ac_platform.identity.models import (
    EmailChallenge,
    EmailLoginCode,
    PasswordCredential,
    Person,
    PersonStatus,
)
from ac_platform.identity.models import (
    Session as IdentitySession,
)
from ac_platform.identity.password_auth import EMAIL_MAX_LENGTH, normalize_email, utc_now
from ac_platform.tenancy.models import Membership, MembershipRole, MembershipStatus

EMAIL_LOGIN_CODE_LENGTH = 6
EMAIL_LOGIN_CODE_TTL = timedelta(minutes=10)
EMAIL_LOGIN_RESEND_AFTER = timedelta(seconds=60)
EMAIL_LOGIN_SEND_WINDOW = timedelta(hours=1)
EMAIL_LOGIN_SEND_LIMIT = 5
EMAIL_LOGIN_ATTEMPT_LIMIT = 5
EMAIL_LOGIN_REQUEST_EVENT = "identity.email_login_code.requested.v1"
EMAIL_LOGIN_REQUEST_JOB = "email.identity_login_code.v1"
_CODE_PATTERN = re.compile(r"[0-9]{6}\Z")


@dataclass(frozen=True, slots=True)
class IssuedEmailLoginCode:
    challenge_id: UUID
    generation_id: UUID


@dataclass(frozen=True, slots=True)
class VerifiedEmailLogin:
    person: Person | None
    account_created: bool = False
    learner_provisioning_required: bool = False
    consent_audit_required: bool = False
    previous_consent_version: str | None = None
    previous_consented_at: datetime | None = None


def _raw_secret(secret: bytes | str) -> bytes:
    return secret.encode("utf-8") if isinstance(secret, str) else secret


def _encryption_key(secret: bytes | str) -> bytes:
    raw = _raw_secret(secret)
    if len(raw) < 32:
        raise ValueError("email challenge secret must contain at least 32 bytes")
    return hashlib.sha256(b"authority-closers:email-login-code:aesgcm:v1:" + raw).digest()


def _code_hash(secret: bytes | str, email: str, code: str) -> bytes:
    raw = _raw_secret(secret)
    if len(raw) < 32:
        raise ValueError("email challenge secret must contain at least 32 bytes")
    message = (
        b"authority-closers:email-login-code:v1:"
        + email.encode("utf-8")
        + b":"
        + code.encode("ascii")
    )
    return hmac.new(raw, message, hashlib.sha256).digest()


def _aad(challenge_id: UUID, generation_id: UUID, email: str) -> bytes:
    return f"email-login-code:v1:{challenge_id}:{generation_id}:{email}".encode()


def _encrypt_code(
    secret: bytes | str,
    code: str,
    *,
    challenge_id: UUID,
    generation_id: UUID,
    email: str,
) -> str:
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(_encryption_key(secret)).encrypt(
        nonce,
        code.encode("ascii"),
        _aad(challenge_id, generation_id, email),
    )
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii").rstrip("=")


def decrypt_email_login_code(
    secret: bytes | str,
    challenge: EmailLoginCode,
    *,
    generation_id: UUID,
) -> str:
    """Decrypt only the current generation for the durable mail worker."""

    raw = base64.urlsafe_b64decode(
        challenge.encrypted_code + "=" * (-len(challenge.encrypted_code) % 4)
    )
    code = (
        AESGCM(_encryption_key(secret))
        .decrypt(
            raw[:12],
            raw[12:],
            _aad(challenge.id, generation_id, challenge.normalized_email),
        )
        .decode("ascii")
    )
    if _CODE_PATTERN.fullmatch(code) is None:
        raise ValueError("decrypted email login code is malformed")
    return code


def _exact_consent(value: str | None, required: str | None) -> str | None:
    submitted = value.strip() if isinstance(value, str) else ""
    configured = required.strip() if isinstance(required, str) else ""
    if not submitted or not configured or len(submitted) > 64 or "\x00" in submitted:
        return None
    if not hmac.compare_digest(submitted.encode("utf-8"), configured.encode("utf-8")):
        return None
    return submitted


class EmailLoginCodeService:
    """Transactional numeric email-code issue and consume operations."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        challenge_secret: bytes | str,
        audit_tenant_id: UUID | None = None,
    ) -> None:
        self.session = session
        self.challenge_secret = challenge_secret
        self.audit_tenant_id = audit_tenant_id

    async def _has_privileged_membership(self, person_id: UUID) -> bool:
        """Never let learner email OTP authenticate an admin identity."""

        privileged_person_id = await self.session.scalar(
            select(Membership.person_id)
            .where(
                Membership.person_id == person_id,
                Membership.status == MembershipStatus.ACTIVE.value,
                Membership.role.in_(
                    (
                        MembershipRole.SUPPORT.value,
                        MembershipRole.ADMIN.value,
                        MembershipRole.OWNER.value,
                    )
                ),
            )
            .limit(1)
        )
        return privileged_person_id is not None

    async def begin(
        self,
        *,
        email: str,
        consent_accepted: bool,
        submitted_consent_version: str | None,
        required_consent_version: str | None,
        age_attested: bool = False,
        now: datetime | None = None,
    ) -> IssuedEmailLoginCode | None:
        normalized_email = normalize_email(email)
        if len(normalized_email) > EMAIL_MAX_LENGTH:
            return None
        current = (now or utc_now()).astimezone(UTC)
        challenge = await self.session.scalar(
            select(EmailLoginCode)
            .where(EmailLoginCode.normalized_email == normalized_email)
            .with_for_update()
        )
        person = await self.session.scalar(
            select(Person).where(func.lower(Person.email) == normalized_email).with_for_update()
        )
        accepted_consent = (
            _exact_consent(submitted_consent_version, required_consent_version)
            if consent_accepted
            else None
        )
        if person is not None:
            if person.status != PersonStatus.ACTIVE.value:
                if challenge is not None and challenge.consumed_at is None:
                    challenge.consumed_at = current
                    await self.session.flush()
                return None
            if await self._has_privileged_membership(person.id):
                if challenge is not None and challenge.consumed_at is None:
                    challenge.consumed_at = current
                    await self.session.flush()
                return None
            # Existing AC identities do not have their consent record rewritten
            # by a sign-in challenge. An unverified pre-registration identity
            # is the exception: mailbox proof may reclaim its untrusted password
            # only after this challenge binds the current explicit consent.
            account_consent = accepted_consent if person.email_verified_at is None else None
            if person.email_verified_at is None and (
                account_consent is None or age_attested is not True
            ):
                return None
        else:
            if accepted_consent is None or age_attested is not True:
                return None
            account_consent = accepted_consent

        if challenge is not None:
            if current < challenge.issued_at + EMAIL_LOGIN_RESEND_AFTER:
                return None
            if current < challenge.send_window_started_at + EMAIL_LOGIN_SEND_WINDOW:
                if (
                    challenge.sends_in_window >= EMAIL_LOGIN_SEND_LIMIT
                    or challenge.failed_attempts >= EMAIL_LOGIN_ATTEMPT_LIMIT
                ):
                    return None
                send_count = challenge.sends_in_window + 1
                window_started_at = challenge.send_window_started_at
                failed_attempts = challenge.failed_attempts
            else:
                send_count = 1
                window_started_at = current
                failed_attempts = 0
            challenge_id = challenge.id
        else:
            challenge_id = uuid4()
            send_count = 1
            window_started_at = current
            failed_attempts = 0

        generation_id = uuid4()
        code = f"{secrets.randbelow(10**EMAIL_LOGIN_CODE_LENGTH):0{EMAIL_LOGIN_CODE_LENGTH}d}"
        token_hash = _code_hash(self.challenge_secret, normalized_email, code)
        encrypted_code = _encrypt_code(
            self.challenge_secret,
            code,
            challenge_id=challenge_id,
            generation_id=generation_id,
            email=normalized_email,
        )
        if challenge is None:
            challenge = EmailLoginCode(
                id=challenge_id,
                generation_id=generation_id,
                normalized_email=normalized_email,
                token_hash=token_hash,
                encrypted_code=encrypted_code,
                consent_version=account_consent,
                age_attested=age_attested is True,
                issued_at=current,
                expires_at=current + EMAIL_LOGIN_CODE_TTL,
                failed_attempts=0,
                send_window_started_at=window_started_at,
                sends_in_window=send_count,
            )
            try:
                async with self.session.begin_nested():
                    self.session.add(challenge)
                    await self.session.flush()
            except IntegrityError:
                # Concurrent first sends serialize at the unique normalized
                # email key. The winner owns the cooldown; do not send twice.
                winner = await self.session.scalar(
                    select(EmailLoginCode)
                    .where(EmailLoginCode.normalized_email == normalized_email)
                    .with_for_update()
                )
                if winner is None:
                    raise
                return None
        else:
            challenge.generation_id = generation_id
            challenge.token_hash = token_hash
            challenge.encrypted_code = encrypted_code
            challenge.consent_version = account_consent
            challenge.age_attested = age_attested is True
            challenge.issued_at = current
            challenge.expires_at = current + EMAIL_LOGIN_CODE_TTL
            challenge.consumed_at = None
            # Resend may rotate the code, but it cannot replenish the
            # aggregate guessing budget for this one-hour send window.
            challenge.failed_attempts = failed_attempts
            challenge.send_window_started_at = window_started_at
            challenge.sends_in_window = send_count
            await self.session.flush()
        return IssuedEmailLoginCode(challenge_id=challenge_id, generation_id=generation_id)

    async def verify(
        self,
        *,
        email: str,
        code: str,
        required_consent_version: str | None,
        now: datetime | None = None,
    ) -> VerifiedEmailLogin:
        normalized_email = normalize_email(email)
        current = (now or utc_now()).astimezone(UTC)
        if _CODE_PATTERN.fullmatch(code) is None:
            return VerifiedEmailLogin(person=None)
        challenge = await self.session.scalar(
            select(EmailLoginCode)
            .where(EmailLoginCode.normalized_email == normalized_email)
            .with_for_update()
        )
        if (
            challenge is None
            or challenge.consumed_at is not None
            or challenge.expires_at <= current
            or challenge.failed_attempts >= EMAIL_LOGIN_ATTEMPT_LIMIT
        ):
            return VerifiedEmailLogin(person=None)
        candidate = _code_hash(self.challenge_secret, normalized_email, code)
        if not hmac.compare_digest(candidate, challenge.token_hash):
            challenge.failed_attempts += 1
            if challenge.failed_attempts >= EMAIL_LOGIN_ATTEMPT_LIMIT:
                challenge.consumed_at = current
            await self.session.flush()
            return VerifiedEmailLogin(person=None)

        person = await self.session.scalar(
            select(Person).where(func.lower(Person.email) == normalized_email).with_for_update()
        )
        if person is not None and person.status != PersonStatus.ACTIVE.value:
            challenge.consumed_at = current
            await self.session.flush()
            return VerifiedEmailLogin(person=None)
        if person is not None and await self._has_privileged_membership(person.id):
            challenge.consumed_at = current
            await self.session.flush()
            return VerifiedEmailLogin(person=None)

        created = False
        if person is None:
            accepted_consent = (
                _exact_consent(challenge.consent_version, required_consent_version)
                if challenge.age_attested is True
                else None
            )
            if accepted_consent is None:
                challenge.consumed_at = current
                await self.session.flush()
                return VerifiedEmailLogin(person=None)
            candidate_person = Person(
                id=uuid4(),
                email=normalized_email,
                email_verified_at=current,
                consent_version=accepted_consent,
                consented_at=current,
            )
            try:
                async with self.session.begin_nested():
                    self.session.add(candidate_person)
                    await self.session.flush()
            except IntegrityError:
                # A concurrent Google/password registration may have claimed
                # this exact address. Resolve that canonical identity rather
                # than creating a second person or merging on profile fields.
                person = await self.session.scalar(
                    select(Person)
                    .where(func.lower(Person.email) == normalized_email)
                    .with_for_update()
                )
                if person is None or person.status != PersonStatus.ACTIVE.value:
                    challenge.consumed_at = current
                    await self.session.flush()
                    return VerifiedEmailLogin(person=None)
            else:
                person = candidate_person
                created = True
        # A concurrent registration can win the unique-email race after the
        # initial lookup. Re-evaluate status and privilege on that canonical
        # person before mailbox proof can issue any session.
        if person.status != PersonStatus.ACTIVE.value or await self._has_privileged_membership(
            person.id
        ):
            challenge.consumed_at = current
            await self.session.flush()
            return VerifiedEmailLogin(person=None)
        first_mailbox_verification = person.email_verified_at is None
        previous_consent_version = person.consent_version
        previous_consented_at = person.consented_at
        if first_mailbox_verification:
            accepted_consent = (
                _exact_consent(challenge.consent_version, required_consent_version)
                if challenge.age_attested is True
                else None
            )
            if accepted_consent is None:
                challenge.consumed_at = current
                await self.session.flush()
                return VerifiedEmailLogin(person=None)
            # A password registration may predate mailbox proof. If its
            # unverified credential was chosen by someone else, verifying the
            # mailbox must not activate that password for the mailbox owner.
            password_credential = await self.session.scalar(
                select(PasswordCredential)
                .where(PasswordCredential.person_id == person.id)
                .with_for_update()
            )
            if password_credential is not None:
                if self.audit_tenant_id is None:
                    challenge.consumed_at = current
                    await self.session.flush()
                    return VerifiedEmailLogin(person=None)
                outstanding_email_challenges = list(
                    (
                        await self.session.scalars(
                            select(EmailChallenge)
                            .where(
                                EmailChallenge.person_id == person.id,
                                EmailChallenge.consumed_at.is_(None),
                            )
                            .with_for_update()
                        )
                    ).all()
                )
                active_sessions = list(
                    (
                        await self.session.scalars(
                            select(IdentitySession)
                            .where(
                                IdentitySession.person_id == person.id,
                                IdentitySession.revoked_at.is_(None),
                            )
                            .with_for_update()
                        )
                    ).all()
                )
                for email_challenge in outstanding_email_challenges:
                    email_challenge.consumed_at = current
                for identity_session in active_sessions:
                    identity_session.revoked_at = current
                    identity_session.revocation_reason = "email_login_identity_reclaimed"
                    identity_session.revision += 1
                await self.session.delete(password_credential)
                await AuditRepository(self.session).append(
                    tenant_id=self.audit_tenant_id,
                    actor_person_id=None,
                    actor_type="system",
                    action="identity.email_login_unverified_credential_reclaimed",
                    resource_type="person",
                    resource_id=person.id,
                    reason=(
                        "The mailbox owner completed a purpose-specific email sign-in challenge."
                    ),
                    payload={
                        "password_credential_removed": True,
                        "email_challenges_consumed": len(outstanding_email_challenges),
                        "sessions_revoked": len(active_sessions),
                    },
                    now=current,
                )
            person.consent_version = accepted_consent
            person.consented_at = current
            person.email_verified_at = current
            person.revision += 1
        challenge.consumed_at = current
        await self.session.flush()
        return VerifiedEmailLogin(
            person=person,
            account_created=created,
            learner_provisioning_required=created or first_mailbox_verification,
            consent_audit_required=created or first_mailbox_verification,
            # Prior consent is change-audit metadata, not a new consent receipt
            # for an already verified account that only signed in.
            previous_consent_version=(
                previous_consent_version if first_mailbox_verification else None
            ),
            previous_consented_at=(previous_consented_at if first_mailbox_verification else None),
        )


__all__ = [
    "EMAIL_LOGIN_ATTEMPT_LIMIT",
    "EMAIL_LOGIN_CODE_TTL",
    "EMAIL_LOGIN_REQUEST_EVENT",
    "EMAIL_LOGIN_REQUEST_JOB",
    "EMAIL_LOGIN_RESEND_AFTER",
    "EMAIL_LOGIN_SEND_LIMIT",
    "EmailLoginCodeService",
    "IssuedEmailLoginCode",
    "VerifiedEmailLogin",
    "decrypt_email_login_code",
]
