"""Printable invoice snapshot, integer paise and hostile text escaping."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

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
    for amount in ("INR 2,117.80", "INR 190.60", "INR 2,499.00"):
        assert amount in html
    assert "INR 0.00" not in html and "IGST @" not in html
    assert "CGST @ 9%" in html and "SGST @ 9%" in html
    assert "@media print" in html and "2026-10-04T00:00:00+00:00" in html
    invoice.details = {
        "seller": {"gstin": "GSTIN pending", "sac": "SAC pending"},
        "buyer": {"name": "Buyer name pending"},
    }
    invoice.place_of_supply = None
    html = render_invoice(invoice)
    assert "GSTIN pending" in html and "SAC pending" in html and "Unknown" in html


def test_invoice_html_labels_parties_service_rates_and_inclusive_total() -> None:
    invoice = BillingInvoice(
        number="EA/2627/00001",
        financial_year="2026-27",
        created_at=datetime(2026, 10, 4, tzinfo=UTC),
        taxable_minor=211780,
        cgst_minor=19060,
        sgst_minor=19060,
        igst_minor=0,
        total_minor=249900,
        details={
            "seller": {
                "name": "Vikriya Solutions LLP (trading as Estate Autopilots)",
                "address": "Fictional registered address",
                "gstin": "27AAAAA0000A1Z0",
                "state_code": "27",
            },
            "buyer": {"name": "Fictional buyer", "gstin": "27BBBBB0000B1Z0", "state_code": "27"},
            "plan_name": "Personal",
            "seats": 1,
            "period_start": "2026-10-04",
            "period_end": "2026-11-04",
        },
    )
    html = render_invoice(invoice)
    assert "Vikriya Solutions LLP (trading as Estate Autopilots)" in html
    for value in ("27AAAAA0000A1Z0", "27BBBBB0000B1Z0"):
        assert f"GSTIN: {value}" in html
    assert html.count("State code: 27") == 2
    assert "Service: Sales Xray — Personal" in html and "Seats: 1" in html
    assert "Period: 2026-10-04 – 2026-11-04" in html and "Reverse charge: No" in html
    assert "<p>Total includes GST</p>" in html and "Price includes GST" not in html
    assert "CGST @ 9%" in html and "SGST @ 9%" in html and "IGST @" not in html
    invoice.cgst_minor = invoice.sgst_minor = 0
    invoice.igst_minor = 38120
    html = render_invoice(invoice)
    assert "IGST @ 18%" in html and "CGST @" not in html and "SGST @" not in html
    # The renderer recovers the rate from the saved amounts, not today's 18%.
    invoice.taxable_minor, invoice.igst_minor, invoice.total_minor = 10000, 500, 10500
    invoice.details["seats"] = 2
    html = render_invoice(invoice)
    assert "IGST @ 5%" in html and "Total includes GST" in html and "INR 105.00" in html


@pytest.mark.parametrize(
    ("plan_name", "seats", "taxable", "cgst", "sgst", "igst", "total", "expected_rows"),
    [
        (
            "Personal",
            1,
            211780,
            19060,
            19060,
            0,
            249900,
            "<tr><th>Taxable value</th><td>INR 2,117.80</td></tr>"
            "<tr><th>CGST @ 9%</th><td>INR 190.60</td></tr>"
            "<tr><th>SGST @ 9%</th><td>INR 190.60</td></tr>"
            "<tr><th>Total</th><td>INR 2,499.00</td></tr>",
        ),
        (
            "Organisation",
            3,
            100000,
            0,
            0,
            18000,
            118000,
            "<tr><th>Taxable value</th><td>INR 1,000.00</td></tr>"
            "<tr><th>IGST @ 18%</th><td>INR 180.00</td></tr>"
            "<tr><th>Total</th><td>INR 1,180.00</td></tr>",
        ),
        (
            "Enterprise",
            50,
            1000000,
            90000,
            90000,
            0,
            1180000,
            "<tr><th>Taxable value</th><td>INR 10,000.00</td></tr>"
            "<tr><th>CGST @ 9%</th><td>INR 900.00</td></tr>"
            "<tr><th>SGST @ 9%</th><td>INR 900.00</td></tr>"
            "<tr><th>Total</th><td>INR 11,800.00</td></tr>",
        ),
    ],
)
def test_invoice_total_wording_preserves_saved_amounts_and_tax_breakdown(
    plan_name: str,
    seats: int,
    taxable: int,
    cgst: int,
    sgst: int,
    igst: int,
    total: int,
    expected_rows: str,
) -> None:
    invoice = BillingInvoice(
        number="EA/2627/00001",
        financial_year="2026-27",
        created_at=datetime(2026, 10, 4, tzinfo=UTC),
        taxable_minor=taxable,
        cgst_minor=cgst,
        sgst_minor=sgst,
        igst_minor=igst,
        total_minor=total,
        details={"plan_name": plan_name, "seats": seats, "buyer": {"name": "Fictional buyer"}},
    )
    html = render_invoice(invoice)
    assert html.count("<p>Total includes GST</p>") == 1 and "Price includes GST" not in html
    assert f"Service: Sales Xray — {plan_name}" in html and f"Seats: {seats}" in html
    assert f'<table aria-label="Invoice amounts"><tbody>{expected_rows}</tbody></table>' in html
