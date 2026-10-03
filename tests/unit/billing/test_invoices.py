"""Invoice calendar, stored GST flag and strict optional buyer input."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ac_platform.billing.invoices import financial_year
from ac_platform.billing.views import MoneyView
from ac_platform.http.billing import BuyerRequest
from tests.unit.http.test_billing_routes import _order


def test_financial_year_changes_at_midnight_in_india():
    assert financial_year(datetime(2027, 3, 31, 18, 29, 59, tzinfo=UTC)) == "2026-27"
    assert financial_year(datetime(2027, 3, 31, 18, 30, tzinfo=UTC)) == "2027-28"
    with pytest.raises(ValueError, match="timezone-aware"):
        financial_year(datetime(2027, 4, 1))


@pytest.mark.parametrize("flag,mode", [(True, "inclusive"), (False, "exclusive")])
def test_order_tax_uses_the_saved_flag_even_when_it_contradicts_the_plan_key(flag, mode):
    order = replace(_order(), plan_key="organisation", amount=MoneyView(249900, "INR", flag))
    assert order.tax.mode == mode
    assert (order.tax.taxable_minor, order.tax.gst_minor) == (211780, 38120)


@pytest.mark.parametrize(
    "fields",
    [
        {"name": " "},
        {"name": "Buyer", "gstin": "bad"},
        {"name": "Buyer", "state_code": "123"},
        {"name": "Buyer", "extra": "refused"},
    ],
)
def test_buyer_input_is_bounded_and_unknown_fields_are_refused(fields):
    with pytest.raises(ValidationError):
        BuyerRequest(**fields)
