"""Issue tax documents inside the verified settlement transaction (ADR 0053)."""

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.application.settings import Settings, get_settings
from ac_platform.billing.errors import BillingValidationFailed
from ac_platform.billing.invoice_models import (
    BillingBuyerTaxDetails,
    BillingCreditNote,
    BillingInvoice,
    BillingInvoiceCounter,
)
from ac_platform.billing.order_models import (
    BillingOrder,
    BillingPaymentEvent,
    BillingRefundEvent,
    BillingSubscription,
)
from ac_platform.billing.tax import tax_from_total


def financial_year(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise ValueError("invoice times must be timezone-aware")
    local = moment.astimezone(ZoneInfo("Asia/Kolkata"))
    year = local.year - (local.month < 4)
    return f"{year}-{(year + 1) % 100:02d}"


async def _number(
    database: AsyncSession,
    model: type[BillingInvoice] | type[BillingCreditNote],
    now: datetime,
    prefix: str,
) -> tuple[str, int, str]:
    year = financial_year(now)
    await database.execute(
        insert(BillingInvoiceCounter).values(financial_year=year).on_conflict_do_nothing()
    )
    await database.scalar(
        select(BillingInvoiceCounter)
        .where(BillingInvoiceCounter.financial_year == year)
        .with_for_update()
    )
    # The locked row is immutable. Rollback consumes no number; supersessions
    # remain counted, and invoices/credit notes have independent sequences.
    sequence = 1 + (
        await database.scalar(select(func.max(model.sequence)).where(model.financial_year == year))
        or 0
    )
    return year, sequence, f"{prefix}/{year}/{sequence:05d}"


async def issue_invoice(
    database: AsyncSession,
    copy: BillingOrder | BillingSubscription,
    payment: BillingPaymentEvent,
    now: datetime,
    settings: Settings | None = None,
) -> BillingInvoice:
    if not payment.payment_ref or payment.amount_minor is None:
        raise BillingValidationFailed(
            "A tax invoice requires a verified payment reference and amount."
        )
    settings = settings or get_settings()
    year, sequence, number = await _number(
        database, BillingInvoice, now, settings.billing_invoice_prefix
    )
    existing = await database.scalar(
        select(BillingInvoice).where(
            BillingInvoice.provider == payment.provider,
            BillingInvoice.payment_ref == payment.payment_ref,
            BillingInvoice.supersedes_id.is_(None),
        )
    )
    if existing is not None:
        return existing
    buyer = await database.scalar(
        select(BillingBuyerTaxDetails)
        .where(BillingBuyerTaxDetails.order_id == payment.order_id)
        .order_by(BillingBuyerTaxDetails.created_at.desc(), BillingBuyerTaxDetails.id.desc())
        .limit(1)
    )
    buyer_details = (
        {"name": "Buyer name pending", "gstin": None, "state_code": None}
        if buyer is None
        else {"name": buyer.name, "gstin": buyer.gstin, "state_code": buyer.state_code}
    )
    tax = tax_from_total(payment.amount_minor, "inclusive" if copy.gst_inclusive else "exclusive")
    interstate = bool(
        buyer_details["state_code"]
        and settings.billing_seller_state_code
        and buyer_details["state_code"] != settings.billing_seller_state_code
    )
    cgst, sgst, igst = tax.components(interstate=interstate)
    invoice = BillingInvoice(
        id=uuid4(),
        account_id=copy.account_id,
        order_id=payment.order_id,
        payment_event_id=payment.id,
        provider=payment.provider,
        payment_ref=payment.payment_ref,
        financial_year=year,
        sequence=sequence,
        number=number,
        supersedes_id=None,
        created_at=now,
        details={
            "seller": {
                "name": settings.billing_seller_legal_name,
                "gstin": settings.billing_seller_gstin or "GSTIN pending",
                "address": settings.billing_seller_registered_address,
                "state_code": settings.billing_seller_state_code,
                "sac": settings.billing_seller_sac or "SAC pending",
            },
            "buyer": buyer_details,
            "tax": asdict(tax) | {"cgst_minor": cgst, "sgst_minor": sgst, "igst_minor": igst},
            "currency": payment.currency,
            "plan_name": copy.plan_name,
            "seats": copy.seats,
            "period_start": None
            if payment.period_start is None
            else payment.period_start.isoformat(),
            "period_end": None if payment.period_end is None else payment.period_end.isoformat(),
        },
    )
    database.add(invoice)
    await database.flush()
    return invoice


async def issue_credit_note(
    database: AsyncSession,
    payment: BillingPaymentEvent,
    refund: BillingRefundEvent,
    now: datetime,
    settings: Settings | None = None,
) -> BillingCreditNote:
    if refund.state != "refunded":
        raise BillingValidationFailed("A credit note requires a verified completed refund.")
    refund_ref = refund.provider_refund_ref or refund.id.hex
    settings = settings or get_settings()
    year, sequence, number = await _number(
        database, BillingCreditNote, now, settings.billing_invoice_prefix + "-CN"
    )
    invoice = await database.scalar(
        select(BillingInvoice).where(
            BillingInvoice.provider == payment.provider,
            BillingInvoice.payment_ref == payment.payment_ref,
            BillingInvoice.supersedes_id.is_(None),
        )
    )
    if invoice is None:
        raise BillingValidationFailed("A verified refund requires its original tax invoice.")
    existing = await database.scalar(
        select(BillingCreditNote).where(
            BillingCreditNote.invoice_id == invoice.id,
            BillingCreditNote.refund_ref == refund_ref,
            BillingCreditNote.supersedes_id.is_(None),
        )
    )
    if existing is not None:
        return existing
    note = BillingCreditNote(
        id=uuid4(),
        account_id=invoice.account_id,
        invoice_id=invoice.id,
        refund_event_id=refund.id,
        refund_ref=refund_ref,
        financial_year=year,
        sequence=sequence,
        number=number,
        supersedes_id=None,
        created_at=now,
        details=deepcopy(invoice.details) | {"invoice_number": invoice.number},
    )
    database.add(note)
    await database.flush()
    return note
