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
            "revision >= 0",
            name="revision_nonnegative",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
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


__all__ = [
    "AccountDeletionRequest",
    "AuthenticationReplay",
    "DeletionRequest",
    "DeletionRequestStatus",
    "Person",
    "PersonStatus",
    "ProviderAuthorizationTransaction",
    "ProviderAuthorizationTransactionStatus",
    "ProviderIdentity",
    "Session",
    "utc_now",
]
