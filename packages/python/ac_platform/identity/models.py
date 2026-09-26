"""SQLAlchemy models for canonical identity and account lifecycle state.

The models intentionally contain no provider SDK or HTTP concerns.  A provider
adapter is expected to hand the application a verified assertion; the
application then uses the provider's immutable ``(issuer, subject)`` key to
resolve the canonical person.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ac_platform.db.base import Base

if TYPE_CHECKING:
    from ac_platform.tenancy.models import Membership


def utc_now() -> datetime:
    """Return an aware UTC timestamp suitable for application-side defaults."""

    return datetime.now(UTC)


class PersonStatus(StrEnum):
    """Lifecycle states that affect authentication without deleting history."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class SessionAudience(StrEnum):
    """The server-owned surface a session is allowed to authenticate."""

    ACCOUNT = "account"
    REVIEWER = "reviewer"


class OnboardingStatus(StrEnum):
    """Progressive self-profile states without implying course entitlement."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class DeletionRequestStatus(StrEnum):
    """Account deletion workflow states represented by the identity module."""

    REQUESTED = "requested"
    PROCESSING = "processing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ProviderAuthorizationTransactionStatus(StrEnum):
    """Lifecycle of a one-time provider authorization transaction."""

    ISSUED = "issued"
    CONSUMED = "consumed"


class Person(Base):
    """Canonical person record shared by all provider identities and tenants."""

    __tablename__ = "persons"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'suspended', 'deleted')",
            name="status",
        ),
        CheckConstraint(
            "email IS NULL OR length(trim(email)) > 0",
            name="email_nonblank",
        ),
        CheckConstraint(
            "display_name IS NULL OR length(trim(display_name)) > 0",
            name="display_name_nonblank",
        ),
        CheckConstraint(
            "first_name IS NULL OR length(trim(first_name)) > 0",
            name="first_name_nonblank",
        ),
        CheckConstraint(
            "whatsapp_number IS NULL OR length(trim(whatsapp_number)) >= 7",
            name="whatsapp_number_min_length",
        ),
        CheckConstraint(
            "consent_version IS NULL OR length(trim(consent_version)) > 0",
            name="consent_version_nonblank",
        ),
        CheckConstraint(
            "experience_context IS NULL OR length(trim(experience_context)) > 0",
            name="experience_context_nonblank",
        ),
        CheckConstraint(
            "learning_goal IS NULL OR length(trim(learning_goal)) > 0",
            name="learning_goal_nonblank",
        ),
        CheckConstraint(
            "practice_situation IS NULL OR length(trim(practice_situation)) > 0",
            name="practice_situation_nonblank",
        ),
        CheckConstraint(
            "weekly_minutes IS NULL OR weekly_minutes BETWEEN 15 AND 1200",
            name="weekly_minutes_bounds",
        ),
        CheckConstraint(
            "onboarding_status IN ('not_started', 'in_progress', 'completed', 'skipped')",
            name="onboarding_status",
        ),
        CheckConstraint(
            "onboarding_step BETWEEN 1 AND 3",
            name="onboarding_step_bounds",
        ),
        CheckConstraint(
            "onboarding_revision >= 0",
            name="onboarding_revision_nonnegative",
        ),
        CheckConstraint(
            "onboarding_status <> 'completed' OR "
            "(experience_context IS NOT NULL AND learning_goal IS NOT NULL)",
            name="onboarding_completed_fields",
        ),
        CheckConstraint(
            "revision >= 0",
            name="revision_nonnegative",
        ),
        Index(
            "uq_persons_email_ci",
            text("lower(email)"),
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
            sqlite_where=text("email IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    whatsapp_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    consent_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    experience_context: Mapped[str | None] = mapped_column(String(64), nullable=True)
    learning_goal: Mapped[str | None] = mapped_column(String(240), nullable=True)
    practice_situation: Mapped[str | None] = mapped_column(String(500), nullable=True)
    weekly_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    onboarding_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=OnboardingStatus.NOT_STARTED.value,
        server_default=OnboardingStatus.NOT_STARTED.value,
    )
    onboarding_step: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    onboarding_revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=PersonStatus.ACTIVE.value,
        server_default=PersonStatus.ACTIVE.value,
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    provider_identities: Mapped[list[ProviderIdentity]] = relationship(
        back_populates="person",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    sessions: Mapped[list[Session]] = relationship(
        back_populates="person",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    deletion_requests: Mapped[list[DeletionRequest]] = relationship(
        back_populates="person",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    password_credential: Mapped[PasswordCredential | None] = relationship(
        back_populates="person",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    email_challenges: Mapped[list[EmailChallenge]] = relationship(
        back_populates="person",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    memberships: Mapped[list[Membership]] = relationship(
        "Membership",
        back_populates="person",
        foreign_keys="Membership.person_id",
        viewonly=True,
    )


class ProviderIdentity(Base):
    """An immutable external identity link for one canonical person."""

    __tablename__ = "provider_identities"
    __table_args__ = (
        UniqueConstraint(
            "issuer",
            "subject",
            name="uq_provider_identities_issuer_subject",
        ),
        CheckConstraint(
            "length(trim(issuer)) > 0",
            name="issuer_nonblank",
        ),
        CheckConstraint(
            "length(trim(subject)) > 0",
            name="subject_nonblank",
        ),
        CheckConstraint(
            "revision >= 0",
            name="revision_nonnegative",
        ),
        Index("ix_provider_identities_person_id", "person_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    person_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("persons.id", name="fk_provider_identities_person_id_persons"),
        nullable=False,
    )
    issuer: Mapped[str] = mapped_column(String(2048), nullable=False)
    subject: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    last_authenticated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    person: Mapped[Person] = relationship(back_populates="provider_identities")


class PasswordCredential(Base):
    """One server-owned password verifier for a canonical person."""

    __tablename__ = "password_credentials"
    __table_args__ = (
        UniqueConstraint("person_id", name="uq_password_credentials_person_id"),
        CheckConstraint("length(trim(password_hash)) > 0", name="password_hash_nonblank"),
        CheckConstraint("revision >= 0", name="revision_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    person_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("persons.id", name="fk_password_credentials_person_id_persons"),
        nullable=False,
    )
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    person: Mapped[Person] = relationship(back_populates="password_credential")


class EmailChallengeKind(StrEnum):
    """Bounded, single-purpose email challenge types."""

    VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"  # noqa: S105


class EmailChallenge(Base):
    """A single-use challenge with only a hash and encrypted delivery token at rest."""

    __tablename__ = "email_challenges"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('email_verification', 'password_reset')",
            name="kind_supported",
        ),
        CheckConstraint("length(token_hash) = 32", name="token_hash_length"),
        CheckConstraint("length(trim(encrypted_token)) > 0", name="encrypted_token_nonblank"),
        CheckConstraint("expires_at > issued_at", name="expiry_after_issue"),
        CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= issued_at",
            name="consumed_after_issue",
        ),
        Index("ix_email_challenges_person_kind", "person_id", "kind", "issued_at"),
        Index("ix_email_challenges_expiry", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    person_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("persons.id", name="fk_email_challenges_person_id_persons"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(length=32), nullable=False, unique=True)
    encrypted_token: Mapped[str] = mapped_column(String(768), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    person: Mapped[Person] = relationship(back_populates="email_challenges")


class EmailLoginCode(Base):
    """Current numeric sign-in challenge and durable per-email send window.

    A row may exist before a canonical person: account creation is deferred
    until the mailbox code is consumed with the current explicit age and Terms
    acknowledgement. Legacy rows default to an unattested state and cannot
    create or first-verify a learner. ``generation_id`` fences already-enqueued
    mail when a resend supersedes the current code.
    """

    __tablename__ = "email_login_codes"
    __table_args__ = (
        CheckConstraint("length(trim(normalized_email)) > 0", name="email_nonblank"),
        CheckConstraint("length(token_hash) = 32", name="token_hash_length"),
        CheckConstraint("length(trim(encrypted_code)) > 0", name="encrypted_code_nonblank"),
        CheckConstraint("expires_at > issued_at", name="expiry_after_issue"),
        CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= issued_at",
            name="consumed_after_issue",
        ),
        CheckConstraint("failed_attempts BETWEEN 0 AND 5", name="failed_attempts_bounds"),
        CheckConstraint("sends_in_window BETWEEN 1 AND 5", name="sends_in_window_bounds"),
        UniqueConstraint("normalized_email", name="uq_email_login_codes_email"),
        UniqueConstraint("generation_id", name="uq_email_login_codes_generation"),
        Index("ix_email_login_codes_expiry", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    generation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    normalized_email: Mapped[str] = mapped_column(String(320), nullable=False)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(length=32), nullable=False)
    encrypted_code: Mapped[str] = mapped_column(String(256), nullable=False)
    consent_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    age_attested: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    send_window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    sends_in_window: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )


class ReviewerAuthChallenge(Base):
    """One-time mailbox proof for a dedicated reviewer session.

    Reviewer sign-in is intentionally separate from learner email challenges:
    an invited address may not have a canonical person yet, and proving the
    invitation must never imply learner consent or membership provisioning.
    ``invitation_id`` is an opaque cross-domain binding resolved by the review
    boundary in the same caller-owned transaction. The browser binding is
    retained only as a domain-separated digest; its raw value is never stored.
    """

    __tablename__ = "reviewer_auth_challenges"
    __table_args__ = (
        CheckConstraint(
            "length(trim(email)) > 3",
            name="email_nonblank",
        ),
        CheckConstraint("length(token_hash) = 32", name="token_hash_length"),
        CheckConstraint(
            "length(browser_nonce_hash) = 32",
            name="browser_nonce_hash_length",
        ),
        CheckConstraint(
            "length(trim(encrypted_token)) > 0",
            name="encrypted_token_nonblank",
        ),
        CheckConstraint("expires_at > issued_at", name="expiry_after_issue"),
        CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= issued_at",
            name="consumed_after_issue",
        ),
        Index("ix_reviewer_auth_challenges_email_issued", "email", "issued_at"),
        Index("ix_reviewer_auth_challenges_invitation", "invitation_id"),
        Index("ix_reviewer_auth_challenges_expiry", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    # The person is optional because a first-time invited reviewer is not a
    # canonical identity until mailbox proof succeeds.
    person_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("persons.id", name="fk_reviewer_auth_challenges_person_id_persons"),
        nullable=True,
    )
    # Deliberately no ORM/database FK: identity must not import the review
    # domain, and the review boundary validates this binding before commit.
    invitation_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(length=32), nullable=False, unique=True)
    browser_nonce_hash: Mapped[bytes] = mapped_column(LargeBinary(length=32), nullable=False)
    encrypted_token: Mapped[str] = mapped_column(String(768), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Session(Base):
    """Opaque browser/session metadata; the bearer token is never persisted."""

    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
        ForeignKeyConstraint(
            ["selected_tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_sessions_selected_membership",
        ),
        CheckConstraint(
            "length(token_hash) = 32",
            name="token_hash_length",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="expiry_after_creation",
        ),
        CheckConstraint(
            "audience IN ('account', 'reviewer')",
            name="audience_supported",
        ),
        CheckConstraint(
            "audience = 'account' OR selected_tenant_id IS NULL",
            name="reviewer_session_unscoped",
        ),
        CheckConstraint(
            "revoked_at IS NULL OR "
            "revocation_reason IS NULL OR "
            "length(trim(revocation_reason)) > 0",
            name="revocation_reason_nonblank",
        ),
        CheckConstraint(
            "revision >= 0",
            name="revision_nonnegative",
        ),
        Index("ix_sessions_person_id", "person_id"),
        Index("ix_sessions_selected_tenant_id", "selected_tenant_id"),
        Index("ix_sessions_audience", "audience"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    person_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("persons.id", name="fk_sessions_person_id_persons"),
        nullable=False,
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(length=32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    audience: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=SessionAudience.ACCOUNT.value,
        server_default=SessionAudience.ACCOUNT.value,
    )
    selected_tenant_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    person: Mapped[Person] = relationship(back_populates="sessions")

    def is_active_at(self, now: datetime) -> bool:
        """Return whether this session can authenticate at ``now``."""

        now = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
        return self.revoked_at is None and self.expires_at > now


class DeletionRequest(Base):
    """Append-oriented request to remove or anonymize a person's account."""

    __tablename__ = "deletion_requests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_deletion_requests_scoped_membership",
        ),
        CheckConstraint(
            "status IN ('requested', 'processing', 'completed', 'cancelled')",
            name="status",
        ),
        CheckConstraint(
            "(status IN ('requested', 'processing') "
            "AND cancelled_at IS NULL AND completed_at IS NULL) OR "
            "(status = 'cancelled' "
            "AND cancelled_at IS NOT NULL AND completed_at IS NULL "
            "AND cancelled_at >= requested_at) OR "
            "(status = 'completed' "
            "AND completed_at IS NOT NULL AND cancelled_at IS NULL "
            "AND completed_at >= requested_at)",
            name="status_timestamps",
        ),
        CheckConstraint(
            "revision >= 0",
            name="revision_nonnegative",
        ),
        Index("ix_deletion_requests_person_id", "person_id"),
        Index(
            "uq_deletion_requests_one_open_per_person",
            "person_id",
            unique=True,
            postgresql_where=text("status IN ('requested', 'processing')"),
            sqlite_where=text("status IN ('requested', 'processing')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    person_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("persons.id", name="fk_deletion_requests_person_id_persons"),
        nullable=False,
    )
    tenant_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=DeletionRequestStatus.REQUESTED.value,
        server_default=DeletionRequestStatus.REQUESTED.value,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    person: Mapped[Person] = relationship(back_populates="deletion_requests")


# Kept as a descriptive alias for callers that prefer the full name.
AccountDeletionRequest = DeletionRequest


class AuthenticationReplay(Base):
    """Durable one-time provider callback replay key.

    Replay keys are intentionally retained after expiry until an explicit
    retention job removes them.  Reusing a provider nonce must never become
    possible merely because the original transaction aged out.
    """

    __tablename__ = "authentication_replays"
    __table_args__ = (
        CheckConstraint(
            "length(trim(replay_key)) > 0",
            name="replay_key_nonblank",
        ),
        CheckConstraint(
            "expires_at > consumed_at",
            name="expiry_after_consumption",
        ),
        Index("ix_authentication_replays_expires_at", "expires_at"),
    )

    replay_key: Mapped[str] = mapped_column(String(1024), primary_key=True)
    consumed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProviderAuthorizationTransaction(Base):
    """One server-issued authorization attempt, with secrets hashed at rest."""

    __tablename__ = "provider_authorization_transactions"
    __table_args__ = (
        CheckConstraint(
            "authorization_type IN ('register', 'authenticate', 'link')",
            name="auth_type_supported",
        ),
        CheckConstraint(
            "status IN ('issued', 'consumed')",
            name="status_supported",
        ),
        CheckConstraint("length(state_hash) = 32", name="state_hash_length"),
        CheckConstraint("length(nonce_hash) = 32", name="nonce_hash_length"),
        CheckConstraint("length(pkce_verifier_hash) = 32", name="pkce_hash_length"),
        CheckConstraint("expires_at > issued_at", name="expiry_after_issue"),
        CheckConstraint(
            "(status = 'issued' AND consumed_at IS NULL) OR "
            "(status = 'consumed' AND consumed_at IS NOT NULL AND consumed_at >= issued_at)",
            name="status_consumption",
        ),
        Index("ix_provider_authorization_transactions_expiry", "expires_at"),
        Index(
            "ix_provider_authorization_transactions_person",
            "person_id",
            "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    authorization_type: Mapped[str] = mapped_column(String(32), nullable=False)
    audience: Mapped[str] = mapped_column(String(2048), nullable=False)
    state_hash: Mapped[bytes] = mapped_column(LargeBinary(length=32), nullable=False)
    nonce_hash: Mapped[bytes] = mapped_column(LargeBinary(length=32), nullable=False)
    pkce_verifier_hash: Mapped[bytes] = mapped_column(LargeBinary(length=32), nullable=False)
    person_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("persons.id", name="fk_provider_authorization_person_id_persons"),
        nullable=True,
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ProviderAuthorizationTransactionStatus.ISSUED.value,
        server_default=ProviderAuthorizationTransactionStatus.ISSUED.value,
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IdentityCommandIdempotency(Base):
    """Durable, indexed command claim/result state for identity mutations.

    Raw caller keys are deliberately not retained.  The application stores a
    SHA-256 digest so retry authority is bounded without turning audit history
    into a queryable command ledger or persisting a bearer-like client value.
    """

    __tablename__ = "identity_command_idempotency"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "actor_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_identity_command_idempotency_actor_membership",
        ),
        UniqueConstraint(
            "tenant_id",
            "actor_person_id",
            "operation",
            "key_digest",
            name="uq_identity_command_idempotency_scope_key",
        ),
        CheckConstraint(
            "operation = 'onboarding_save'",
            name="operation_supported",
        ),
        CheckConstraint(
            "status IN ('pending', 'completed')",
            name="status",
        ),
        CheckConstraint("length(key_digest) = 64", name="key_digest_sha256"),
        CheckConstraint("length(request_digest) = 64", name="request_digest_sha256"),
        CheckConstraint(
            "(status = 'pending' AND result_revision IS NULL "
            "AND result_updated_at IS NULL AND completed_at IS NULL) OR "
            "(status = 'completed' AND result_revision IS NOT NULL "
            "AND result_revision >= 1 AND result_updated_at IS NOT NULL "
            "AND completed_at IS NOT NULL)",
            name="result_state_complete",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    actor_person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    key_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    result_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = [
    "AccountDeletionRequest",
    "AuthenticationReplay",
    "DeletionRequest",
    "DeletionRequestStatus",
    "EmailChallenge",
    "EmailChallengeKind",
    "EmailLoginCode",
    "ReviewerAuthChallenge",
    "IdentityCommandIdempotency",
    "OnboardingStatus",
    "Person",
    "PersonStatus",
    "ProviderAuthorizationTransaction",
    "ProviderAuthorizationTransactionStatus",
    "ProviderIdentity",
    "PasswordCredential",
    "Session",
    "SessionAudience",
    "utc_now",
]
