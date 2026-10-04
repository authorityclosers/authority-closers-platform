"""Printable invoice snapshot, integer paise and hostile text escaping."""

from datetime import UTC, datetime
from uuid import uuid4

from ac_platform.billing.invoice_models import BillingInvoice
from ac_platform.billing.invoice_render import render_invoice


def test_invoice_html_escapes_every_snapshot_field_and_uses_saved_money() -> None:
    hostile = '<script>alert("fictional")</script>&'
    invoice = BillingInvoice(
        id=uuid4(),
        number="EA/2627/00001",
        financial_year="2026-27",
        created_at=datetime(2026, 10, 4, tzinfo=UTC),
        taxable_minor=211780,
        cgst_minor=19060,
        sgst_minor=19060,
        igst_minor=0,
        total_minor=249900,
        place_of_supply="29",
        details={
            "seller": {key: hostile for key in ("name", "address", "gstin", "state_code", "sac")},
            "buyer": {key: hostile for key in ("name", "gstin", "state_code")},
            **{key: hostile for key in ("plan_name", "seats", "period_start", "period_end")},
        },
    )
    html = render_invoice(invoice)
    assert html.startswith("<!doctype html>") and '<html lang="en">' in html
    assert hostile not in html and "<script>" not in html
    assert html.count("&lt;script&gt;alert(&quot;fictional&quot;)&lt;/script&gt;&amp;") == 12
    for amount in ("INR 2,117.80", "INR 190.60", "INR 0.00", "INR 2,499.00"):
        assert amount in html
    assert "@media print" in html and "2026-10-04T00:00:00+00:00" in html
    invoice.details = {
        "seller": {"gstin": "GSTIN pending", "sac": "SAC pending"},
        "buyer": {"name": "Buyer name pending"},
    }
    invoice.place_of_supply = None
    html = render_invoice(invoice)
    assert "GSTIN pending" in html and "SAC pending" in html and "Unknown" in html
