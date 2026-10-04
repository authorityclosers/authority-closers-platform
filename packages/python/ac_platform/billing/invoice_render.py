"""Print-ready HTML from the immutable invoice snapshot; all text is escaped."""

from datetime import UTC
from html import escape

from ac_platform.billing.invoice_models import BillingInvoice


def render_invoice(invoice: BillingInvoice) -> str:
    def text(value: object) -> str:
        return escape("" if value is None else str(value), quote=True)

    def money(paise: int) -> str:
        return f"INR {paise // 100:,}.{paise % 100:02d}"

    def party(key: str) -> str:
        snapshot = invoice.details.get(key, {})
        return "<br>".join(
            text(value)
            for value in (
                snapshot.get("name"),
                snapshot.get("address"),
                snapshot.get("gstin"),
                snapshot.get("state_code"),
            )
            if value
        )

    seller = invoice.details.get("seller", {})
    amounts = "".join(
        f"<tr><th>{label}</th><td>{money(amount)}</td></tr>"
        for label, amount in (
            ("Taxable value", invoice.taxable_minor),
            ("CGST", invoice.cgst_minor),
            ("SGST", invoice.sgst_minor),
            ("IGST", invoice.igst_minor),
            ("Total", invoice.total_minor),
        )
    )
    issued = invoice.created_at.astimezone(UTC).isoformat()
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tax invoice {text(invoice.number)}</title>
<style>
body {{ font: 16px/1.5 system-ui, sans-serif; max-width: 48rem; margin: 2rem auto; padding: 1rem; }}
h1 {{ font-size: 1.6rem; }} table {{ width: 100%; border-collapse: collapse; }}
th, td {{ border-bottom: 1px solid #777; padding: .5rem; text-align: left; }}
td {{ text-align: right; }} address {{ font-style: normal; white-space: pre-line; }}
@media print {{ body {{ margin: 0; max-width: none; }} tr {{ break-inside: avoid; }} }}
</style></head><body>
<h1>Tax invoice {text(invoice.number)}</h1>
<p>Issued: {text(issued)}<br>Financial year: {text(invoice.financial_year)}</p>
<h2>Seller</h2><address>{party("seller")}</address>
<h2>Buyer</h2><address>{party("buyer")}</address>
<p>Place of supply (state code): {text(invoice.place_of_supply or "Unknown")}<br>
SAC: {text(seller.get("sac") or "SAC pending")}</p>
<p>{text(invoice.details.get("plan_name"))}<br>
Seats: {text(invoice.details.get("seats"))}<br>
Period: {text(invoice.details.get("period_start"))} – {text(invoice.details.get("period_end"))}</p>
<table aria-label="Invoice amounts"><tbody>{amounts}</tbody></table>
</body></html>"""
