"""Immutable tax documents and checkout buyer snapshots (ADR 0053)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
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


def _tax_checks() -> tuple[CheckConstraint, ...]:
    return (
        CheckConstraint("number ~ '^[A-Za-z0-9/-]{1,16}$'", name="number_shape").ddl_if(
            dialect="postgresql"
        ),
        CheckConstraint("currency = 'INR'", name="currency_inr"),
        CheckConstraint(
            "taxable_minor >= 0 AND cgst_minor >= 0 AND sgst_minor >= 0 "
            "AND igst_minor >= 0 AND total_minor >= 0",
            name="money_nonnegative",
        ),
        CheckConstraint(
            "total_minor = taxable_minor + cgst_minor + sgst_minor + igst_minor",
            name="amount_balanced",
        ),
        CheckConstraint(
            "igst_minor = 0 OR (cgst_minor = 0 AND sgst_minor = 0)", name="tax_components"
        ),
    )


class BillingInvoiceCounter(Base):
    """One immutable financial-year mutex; sequences live in document rows."""

    __tablename__ = "billing_invoice_counters"
    financial_year: Mapped[str] = mapped_column(String(7), primary_key=True)


class BillingBuyerTaxDetails(Base):
    __tablename__ = "billing_buyer_tax_details"
    __table_args__ = (
        Index(
            "uq_billing_buyer_order",
            "order_id",
            unique=True,
            postgresql_where=text("supersedes_id IS NULL"),
            sqlite_where=text("supersedes_id IS NULL"),
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("billing_orders.id"))
    name: Mapped[str] = mapped_column(String(200))
    gstin: Mapped[str | None] = mapped_column(String(15))
    state_code: Mapped[str | None] = mapped_column(String(2))
    supersedes_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("billing_buyer_tax_details.id"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TaxDocument(Base):
    __abstract__ = True
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("billing_accounts.id"))
    financial_year: Mapped[str] = mapped_column(
        ForeignKey("billing_invoice_counters.financial_year")
    )
    sequence: Mapped[int] = mapped_column(Integer)
    number: Mapped[str] = mapped_column(String(16), unique=True)
    currency: Mapped[str] = mapped_column(String(3))
    taxable_minor: Mapped[int] = mapped_column(BigInteger)
    cgst_minor: Mapped[int] = mapped_column(BigInteger)
    sgst_minor: Mapped[int] = mapped_column(BigInteger)
    igst_minor: Mapped[int] = mapped_column(BigInteger)
    total_minor: Mapped[int] = mapped_column(BigInteger)
    place_of_supply: Mapped[str | None] = mapped_column(String(2))
    details: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BillingInvoice(TaxDocument):
    __tablename__ = "billing_invoices"
    __table_args__ = (
        *_tax_checks(),
        CheckConstraint("sequence > 0", name="sequence_positive"),
        UniqueConstraint("financial_year", "sequence"),
        Index(
            "uq_billing_invoice_payment",
            "provider",
            "payment_ref",
            unique=True,
            postgresql_where=text("supersedes_id IS NULL"),
            sqlite_where=text("supersedes_id IS NULL"),
        ),
    )
    order_id: Mapped[UUID | None] = mapped_column(ForeignKey("billing_orders.id"))
    payment_event_id: Mapped[UUID] = mapped_column(ForeignKey("billing_payment_events.id"))
    provider: Mapped[str] = mapped_column(String(32))
    payment_ref: Mapped[str] = mapped_column(String(64))
    supersedes_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("billing_invoices.id"), unique=True
    )


class BillingCreditNote(TaxDocument):
    __tablename__ = "billing_credit_notes"
    __table_args__ = (
        *_tax_checks(),
        CheckConstraint("sequence > 0", name="sequence_positive"),
        UniqueConstraint("financial_year", "sequence"),
        Index(
            "uq_billing_credit_refund",
            "invoice_id",
            "refund_ref",
            unique=True,
            postgresql_where=text("supersedes_id IS NULL"),
            sqlite_where=text("supersedes_id IS NULL"),
        ),
    )
    invoice_id: Mapped[UUID] = mapped_column(ForeignKey("billing_invoices.id"))
    refund_event_id: Mapped[UUID] = mapped_column(ForeignKey("billing_refund_events.id"))
    refund_ref: Mapped[str] = mapped_column(String(64))
    supersedes_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("billing_credit_notes.id"), unique=True
    )
