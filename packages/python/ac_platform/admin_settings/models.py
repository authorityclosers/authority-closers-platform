"""Staff keys (Admin CLI and MCP): one key per row, each tied to its own session."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


class AdminStaffKey(Base):
    """A verified control account's key for the Admin command line and MCP.

    Only the SHA-256 of the key is kept; the key is shown once. Rows are never deleted:
    only last use and revocation change.
    """

    __tablename__ = "admin_staff_keys"
    __table_args__ = (
        UniqueConstraint("prefix", name="uq_admin_staff_key_prefix"),
        UniqueConstraint("secret_sha256", name="uq_admin_staff_key_secret"),
        UniqueConstraint("session_id", name="uq_admin_staff_key_session"),
        CheckConstraint("length(secret_sha256) = 64", name="secret_digest"),
        CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        CheckConstraint(
            "(revoked_at IS NULL) = (revoked_by_person_id IS NULL)", name="revocation_by"
        ),
        Index("ix_admin_staff_key_person", "person_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"))
    person_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("persons.id"))
    session_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("sessions.id"))
    name: Mapped[str] = mapped_column(String(80))
    prefix: Mapped[str] = mapped_column(String(24))
    secret_sha256: Mapped[str] = mapped_column(String(64))
    scopes: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by_person_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("persons.id"))

    def view(self, now: datetime) -> dict[str, Any]:
        state = (
            "revoked"
            if self.revoked_at is not None
            else "expired"
            if self.expires_at <= now
            else "active"
        )
        return {
            "id": str(self.id),
            "name": self.name,
            "prefix": self.prefix,
            "scopes": list(self.scopes),
            "state": state,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "last_used_at": None if self.last_used_at is None else self.last_used_at.isoformat(),
            "revoked_at": None if self.revoked_at is None else self.revoked_at.isoformat(),
        }
