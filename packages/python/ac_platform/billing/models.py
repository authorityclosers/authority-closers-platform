"""Billing accounts and the append-only capacity ledger (ADR 0052).

The ledger stores capacity, never use. Positive rows are lots (granted seconds
with a validity window); negative rows are closings written against one lot.
Use stays in the reservation and settlement tables and is allocated by the
projection. Both tables carry database triggers that refuse UPDATE and DELETE.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base

ACCOUNT_KINDS = ("personal", "organisation")
LOT_KINDS = ("period_grant", "purchase", "grant")
CLOSING_KINDS = ("expiry", "refund_hold", "refund")
ENTRY_KINDS = (*LOT_KINDS, "correction", *CLOSING_KINDS, "refund_hold_release")
ACTOR_TYPES = ("person", "system", "provider")
_LOTS = "('period_grant', 'purchase', 'grant')"
_CLOSINGS = "('expiry', 'refund_hold', 'refund')"


class BillingAccount(Base):
    """Personal = (public learner tenant, person); Organisation = (org tenant, no person)."""

    __tablename__ = "billing_accounts"
    __table_args__ = (
        CheckConstraint("kind IN ('personal', 'organisation')", name="kind_supported"),
        CheckConstraint(
            "(kind = 'personal' AND person_id IS NOT NULL) OR "
            "(kind = 'organisation' AND person_id IS NULL)",
            name="kind_owner",
        ),
        UniqueConstraint("tenant_id", "person_id"),
        Index(
            "ix_billing_accounts_organisation",
            "tenant_id",
            unique=True,
            postgresql_where=text("person_id IS NULL"),
            sqlite_where=text("person_id IS NULL"),
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="RESTRICT"))
    person_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("persons.id"))
    kind: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BillingLedgerEntry(Base):
    """One immutable ledger row: a lot, a closing on a lot, or a hold release."""

    __tablename__ = "billing_ledger_entries"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('period_grant', 'purchase', 'grant', 'correction', "
            "'expiry', 'refund_hold', 'refund', 'refund_hold_release')",
            name="kind_supported",
        ),
        CheckConstraint(
            f"(kind IN {_LOTS} AND seconds > 0 AND lot_id IS NULL AND hold_id IS NULL) OR "
            f"(kind IN {_CLOSINGS} AND seconds < 0 AND lot_id IS NOT NULL AND hold_id IS NULL)"
            " OR (kind = 'correction' AND seconds > 0 AND lot_id IS NULL AND hold_id IS NULL)"
            " OR (kind = 'correction' AND seconds < 0 AND lot_id IS NOT NULL AND hold_id IS NULL)"
            " OR (kind = 'refund_hold_release' AND seconds > 0 AND lot_id IS NOT NULL"
            " AND hold_id IS NOT NULL)",
            name="kind_shape",
        ),
        CheckConstraint("expires_at IS NULL OR expires_at > valid_from", name="window"),
        CheckConstraint(
            "actor_type IN ('person', 'system', 'provider')", name="actor_type_supported"
        ),
        CheckConstraint("length(source_ref) >= 3", name="source_ref_length"),
        UniqueConstraint("source_ref"),
        Index("ix_billing_ledger_entries_account", "account_id", "created_at"),
        Index("ix_billing_ledger_entries_lot", "lot_id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("billing_accounts.id", ondelete="RESTRICT")
    )
    kind: Mapped[str] = mapped_column(String(24))
    seconds: Mapped[int] = mapped_column(Integer)
    lot_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("billing_ledger_entries.id"))
    hold_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("billing_ledger_entries.id"))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    plan_key: Mapped[str | None] = mapped_column(String(40))
    source_ref: Mapped[str] = mapped_column(String(160))
    actor_type: Mapped[str] = mapped_column(String(32))
    actor_person_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("persons.id"))
    reason: Mapped[str | None] = mapped_column(String(500))
    audit_event_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("audit_events.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


__all__ = [
    "ACCOUNT_KINDS",
    "ACTOR_TYPES",
    "CLOSING_KINDS",
    "ENTRY_KINDS",
    "LOT_KINDS",
    "BillingAccount",
    "BillingLedgerEntry",
]
