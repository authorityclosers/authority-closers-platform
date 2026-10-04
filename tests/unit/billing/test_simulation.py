from dataclasses import replace

from ac_platform.billing.simulation import payment_page
from tests.unit.http.test_billing_routes import _order


def test_page_escapes_summary_and_keeps_choices_off_a_paid_order() -> None:
    order = replace(_order(), plan_name='<script>alert("fictional")</script>')
    page = payment_page(order, "a" * 64, "https://salesxray.example.test/return")
    assert "Test payment · no money moves" in page
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert all(f">{choice}</button>" in page for choice in ("Pay", "Fail", "Cancel"))
    assert "<form" not in payment_page(replace(order, status="paid"), "a" * 64, "/return")
