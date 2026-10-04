"""Print-ready HTML from immutable tax document snapshots; all text is escaped."""

from datetime import UTC
from html import escape

from ac_platform.billing.invoice_models import BillingCreditNote, BillingInvoice, TaxDocument


def render_invoice(invoice: BillingInvoice) -> str:
    return _render_document(invoice, "Tax invoice")


def render_credit_note(note: BillingCreditNote) -> str:
    invoice_number = escape(str(note.details.get("invoice_number") or note.invoice_id), quote=True)
    reference = (
        f"<p>Original invoice: {invoice_number}<br>"
        f"Refund reference: {escape(note.refund_ref, quote=True)}</p>"
    )
    return _render_document(note, "Credit note", reference)


def _render_document(invoice: TaxDocument, kind: str, reference: str = "") -> str:
    amounts_label = "Invoice" if kind == "Tax invoice" else kind

    def text(value: object) -> str:
        return escape("" if value is None else str(value), quote=True)

    def money(paise: int) -> str:
        return f"INR {paise // 100:,}.{paise % 100:02d}"

    def party(key: str) -> str:
        snapshot = invoice.details.get(key, {})
        return "<br>".join(
            label + text(value)
            for label, value in (
                ("", snapshot.get("name")),
                ("", snapshot.get("address")),
                ("GSTIN: ", snapshot.get("gstin")),
                ("State code: ", snapshot.get("state_code")),
            )
            if value
        )

    seller = invoice.details.get("seller", {})
    taxes = []
    for label, amount in (
        ("CGST", invoice.cgst_minor),
        ("SGST", invoice.sgst_minor),
        ("IGST", invoice.igst_minor),
    ):
        if amount:
            # Recover whole-percent rates from saved paise, half-up to remove
            # invoice rounding; never read the current catalogue or settings.
            rate = (
                (amount * 100 + invoice.taxable_minor // 2) // invoice.taxable_minor
                if invoice.taxable_minor
                else 0
            )
            taxes.append((f"{label} @ {rate}%", amount))
    gst = invoice.cgst_minor + invoice.sgst_minor + invoice.igst_minor
    includes_gst = (
        "<p>Total includes GST</p>" if invoice.taxable_minor + gst == invoice.total_minor else ""
    )
    amounts = "".join(
        f"<tr><th>{label}</th><td>{money(amount)}</td></tr>"
        for label, amount in (
            ("Taxable value", invoice.taxable_minor),
            *taxes,
            ("Total", invoice.total_minor),
        )
    )
    issued = invoice.created_at.astimezone(UTC).isoformat()
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{kind} {text(invoice.number)}</title>
<style>
body {{ font: 16px/1.5 system-ui, sans-serif; max-width: 48rem; margin: 2rem auto; padding: 1rem; }}
h1 {{ font-size: 1.6rem; }} table {{ width: 100%; border-collapse: collapse; }}
th, td {{ border-bottom: 1px solid #777; padding: .5rem; text-align: left; }}
td {{ text-align: right; }} address {{ font-style: normal; white-space: pre-line; }}
@media print {{ body {{ margin: 0; max-width: none; }} tr {{ break-inside: avoid; }} }}
</style></head><body>
<h1>{kind} {text(invoice.number)}</h1>
<p>Issued: {text(issued)}<br>Financial year: {text(invoice.financial_year)}</p>
{reference}
<h2>Seller</h2><address>{party("seller")}</address>
<h2>Buyer</h2><address>{party("buyer")}</address>
<p>Place of supply (state code): {text(invoice.place_of_supply or "Unknown")}<br>
SAC: {text(seller.get("sac") or "SAC pending")}<br>Reverse charge: No</p>
<p>Service: Sales Xray — {text(invoice.details.get("plan_name"))}<br>
Seats: {text(invoice.details.get("seats"))}<br>
Period: {text(invoice.details.get("period_start"))} – {text(invoice.details.get("period_end"))}</p>
{includes_gst}<table aria-label="{amounts_label} amounts"><tbody>{amounts}</tbody></table>
</body></html>"""
