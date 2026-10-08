"""SQLAlchemy models for tenant ownership and membership state."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
    func,
    text,
)
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapped, Mapper, mapped_column, relationship

from ac_platform.db.base import Base
from ac_platform.identity.models import Person


def utc_now() -> datetime:
    """Return an aware UTC timestamp suitable for application-side defaults."""

    return datetime.now(UTC)


class TenantStatus(StrEnum):
    """Lifecycle state for an organization boundary."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class MembershipRole(StrEnum):
    """Roles supported by the first-slice tenant-context policy."""

    LEARNER = "learner"
    SUPPORT = "support"
    ADMIN = "admin"
    OWNER = "owner"
    MEMBER = "member"


class MembershipStatus(StrEnum):
    """Membership lifecycle state independent of the tenant lifecycle."""

    ACTIVE = "active"
    INACTIVE = "inactive"


class Tenant(Base):
    """Organization boundary used by all tenant-scoped application state."""

    __tablename__ = "tenants"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_tenants_slug"),
        CheckConstraint(
            "length(trim(slug)) > 0",
            name="slug_nonblank",
        ),
        CheckConstraint(
            "length(trim(name)) > 0",
            name="name_nonblank",
        ),
        CheckConstraint(
            "status IN ('active', 'suspended', 'deleted')",
            name="status",
        ),
        CheckConstraint("revision >= 0", name="revision_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(63), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=TenantStatus.ACTIVE.value,
        server_default=TenantStatus.ACTIVE.value,
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

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="tenant",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Membership(Base):
    """Tenant-safe person membership with a composite tenant/person key."""

    __tablename__ = "memberships"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_memberships_tenant_id_tenants",
        ),
        ForeignKeyConstraint(
            ["person_id"],
            ["persons.id"],
            name="fk_memberships_person_id_persons",
        ),
        CheckConstraint(
            "role IN ('learner', 'support', 'admin', 'owner', 'processing', 'member')",
            name="role_supported",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="status",
        ),
        CheckConstraint(
            "status = 'active' OR ended_at IS NOT NULL",
            name="inactive_has_end",
        ),
        CheckConstraint(
            "status = 'inactive' OR ended_at IS NULL",
            name="active_has_no_end",
        ),
        CheckConstraint("revision >= 0", name="revision_nonnegative"),
        Index("ix_memberships_person_status", "person_id", "status"),
        Index("ix_memberships_tenant_status", "tenant_id", "status"),
    )

    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    role: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=MembershipRole.LEARNER.value,
        server_default=MembershipRole.LEARNER.value,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=MembershipStatus.ACTIVE.value,
        server_default=MembershipStatus.ACTIVE.value,
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
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    tenant: Mapped[Tenant] = relationship(back_populates="memberships")
    person: Mapped[Person] = relationship(back_populates="memberships")


class Organisation(Base):
    """Registry marker for tenant boundaries managed as an organisation."""

    __tablename__ = "organisations"
    __table_args__ = (
        UniqueConstraint("creation_command_id", name="uq_organisations_creation_command_id"),
        CheckConstraint(
            "length(domain_verification_token) >= 43",
            name="domain_verification_token_min_length",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), primary_key=True
    )
    created_by_person_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("persons.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    creation_command_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    domain_verification_token: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, str]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
    logo_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)


class OrganisationDomainSetting(Base):
    """Append-only, versioned verified-domain and auto-join configuration."""

    __tablename__ = "organisation_domain_settings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"], ["organisations.tenant_id"], name="fk_org_domain_settings_organisation"
        ),
        UniqueConstraint("tenant_id", "version", name="uq_org_domain_settings_tenant_version"),
        UniqueConstraint("command_id", name="uq_org_domain_settings_command_id"),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    verified_domains: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    auto_join: Mapped[bool] = mapped_column(Boolean, nullable=False)
    proof: Mapped[dict[str, dict[str, str]]] = mapped_column(JSON, nullable=False)
    actor_person_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("persons.id"), nullable=True
    )
    operator_reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    command_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


class OrganisationDomainHistoryMutationError(RuntimeError):
    """Domain verification history must be superseded with a new version."""


@event.listens_for(OrganisationDomainSetting, "before_update")
@event.listens_for(OrganisationDomainSetting, "before_delete")
def _reject_organisation_domain_history_mutation(
    mapper: Mapper[Any],
    connection: Connection,
    target: OrganisationDomainSetting,
) -> None:
    del mapper, connection, target
    raise OrganisationDomainHistoryMutationError(
        "organisation domain settings are append-only; add a new version"
    )


class OrganisationInvite(Base):
    """Invitation lifecycle and accepted member command history."""

    __tablename__ = "organisation_invites"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"], ["organisations.tenant_id"], name="fk_org_invites_organisation"
        ),
        CheckConstraint("role IN ('admin', 'member')", name="role_supported"),
        CheckConstraint("status IN ('pending', 'accepted', 'revoked')", name="status_supported"),
        UniqueConstraint("command_id", name="uq_org_invites_command_id"),
        Index(
            "uq_org_invites_pending_email",
            "tenant_id",
            "email_normalized",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    email_normalized: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    invited_by_person_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("persons.id"), nullable=True
    )
    command_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_person_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("persons.id"), nullable=True
    )


__all__ = [
    "Membership",
    "MembershipRole",
    "MembershipStatus",
    "Organisation",
    "OrganisationDomainSetting",
    "OrganisationDomainHistoryMutationError",
    "OrganisationInvite",
    "Tenant",
    "TenantStatus",
    "utc_now",
]
