"""Fictional GST vectors and exact-paise invariants for AUT-878."""

import pytest

from ac_platform.billing.catalogue import tax_mode
from ac_platform.billing.errors import NotOnSale
from ac_platform.billing.tax import calculate_tax, tax_from_total


@pytest.mark.parametrize(
    "plan,price,taxable,gst,total",
    [
        ("personal", 249900, 211780, 38120, 249900),
        ("personal", 2699000, 2287288, 411712, 2699000),
        ("personal", 29900, 25339, 4561, 29900),
        ("organisation", 2000000, 2000000, 360000, 2360000),
        ("organisation", 129900, 129900, 23382, 153282),
        ("enterprise", 50000000, 50000000, 9000000, 59000000),
        ("enterprise", 129900, 129900, 23382, 153282),
    ],
)
def test_catalogue_price_vectors(plan, price, taxable, gst, total):
    result = calculate_tax(price, tax_mode(plan))
    assert (result.taxable_minor, result.gst_minor, result.total_minor) == (taxable, gst, total)
    assert result.rate_basis_points == 1800
    assert tax_from_total(total, result.mode) == result


def test_half_up_once_on_the_total_and_exact_component_split():
    result = calculate_tax(25, "exclusive")  # 4.5 paise rounds to 5.
    assert (result.taxable_minor, result.gst_minor, result.total_minor) == (25, 5, 30)
    assert result.components(interstate=False) == (2, 3, 0)
    assert result.components(interstate=True) == (0, 0, 5)
    inclusive = calculate_tax(59, "inclusive")
    assert (inclusive.taxable_minor, inclusive.gst_minor) == (50, 9)
    assert calculate_tax(3 * 2, "exclusive").gst_minor == 1
    assert calculate_tax(3, "exclusive").gst_minor * 2 == 2


def test_exact_arithmetic_and_saved_totals_do_not_lose_paise():
    for amount in [*range(1001), 10**30 + 25]:
        exclusive = calculate_tax(amount, "exclusive")
        assert tax_from_total(exclusive.total_minor, "exclusive") == exclusive
        inclusive = calculate_tax(amount, "inclusive")
        assert inclusive.taxable_minor + inclusive.gst_minor == amount
        assert sum(inclusive.components(interstate=False)) == inclusive.gst_minor


@pytest.mark.parametrize("amount", [-1, 1.0, True, "100", None])
def test_invalid_amounts_are_refused(amount):
    with pytest.raises(ValueError, match="integer paise"):
        calculate_tax(amount, "exclusive")
    with pytest.raises(ValueError, match="integer paise"):
        tax_from_total(amount, "inclusive")


def test_unknown_tax_treatment_is_not_assumed():
    with pytest.raises(NotOnSale):
        tax_mode("unapproved")
    with pytest.raises(ValueError, match="unknown GST mode"):
        calculate_tax(100, "unknown")
