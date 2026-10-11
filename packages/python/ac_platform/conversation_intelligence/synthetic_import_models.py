"""Explicit sandbox flag and isolated authored content, outside real call accounting."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


class ConversationSandboxOrganisation(Base):
    """Presence is the immutable opt-in flag, set only through an approved data change."""

    __tablename__ = "conversation_sandbox_organisations"
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organisations.tenant_id"), primary_key=True
    )
    approved_by_person_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("persons.id"))
    approval_reference: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationSyntheticRecord(Base):
    __tablename__ = "conversation_synthetic_records"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="positive_revision"),
        CheckConstraint("length(payload_sha256) = 64", name="payload_hash"),
        CheckConstraint("synthetic_key LIKE 'syn-%'", name="synthetic_identity"),
        CheckConstraint("business_id LIKE 'syn-%'", name="synthetic_business"),
        Index(
            "ix_conversation_synthetic_records_date",
            "tenant_id",
            "kind",
            "occurred_at",
            "synthetic_key",
        ),
    )
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversation_sandbox_organisations.tenant_id"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    synthetic_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[str] = mapped_column(String(160))
    imported_by_person_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("persons.id"))
    payload_sha256: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
