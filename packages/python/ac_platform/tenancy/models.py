"""SQLAlchemy models for tenant ownership and membership state."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
            "role IN ('learner', 'support', 'admin', 'owner')",
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


__all__ = [
    "Membership",
    "MembershipRole",
    "MembershipStatus",
    "Tenant",
    "TenantStatus",
    "utc_now",
]
