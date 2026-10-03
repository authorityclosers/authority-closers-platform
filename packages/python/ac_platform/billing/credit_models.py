"""Exact credit quantities, independent of the capacity and usage ledgers."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


class BillingCreditEntry(Base):
    __tablename__ = "billing_credit_entries"
    __table_args__ = (
        CheckConstraint(
            "quantity <> 0 AND quantity > '-Infinity' AND quantity < 'Infinity'",
            name="quantity_finite_nonzero",
        ),
        CheckConstraint("actor_type IN ('person', 'system')", name="actor_type_supported"),
        CheckConstraint(
            "actor_type <> 'person' OR actor_person_id IS NOT NULL", name="actor_attributable"
        ),
        CheckConstraint("length(trim(source_ref)) BETWEEN 3 AND 160", name="source_ref_length"),
        CheckConstraint("length(trim(reason)) BETWEEN 1 AND 500", name="reason_length"),
        UniqueConstraint("source_ref"),
        Index("ix_billing_credit_entries_account", "tenant_id", "account_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="RESTRICT"))
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("billing_accounts.id", ondelete="RESTRICT")
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric())
    source_ref: Mapped[str] = mapped_column(String(160))
    corrected_entry_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("billing_credit_entries.id", ondelete="RESTRICT")
    )
    actor_type: Mapped[str] = mapped_column(String(32))
    actor_person_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("persons.id"))
    reason: Mapped[str] = mapped_column(String(500))
    audit_event_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("audit_events.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
