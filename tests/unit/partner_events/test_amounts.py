"""Our own reader for amounts, sizes and counts said in a call (fictional phrases)."""

from decimal import Decimal

import pytest

from ac_platform.partner_events.amounts import (
    amount_inr,
    gst_basis,
    mentions_price,
    numbers_in,
    system_size,
)


@pytest.mark.parametrize(
    "words,expected",
    [
        ("3.70 lakh", 370_000),
        ("3.7 L", 370_000),
        ("₹3.7L", 370_000),
        ("Rs. 3,70,000", 370_000),
        ("370000", 370_000),
        ("45k", 45_000),
        ("45 thousand", 45_000),
        ("45000/-", 45_000),
        ("1.2 crore", 12_000_000),
        ("0.5 lakh", 50_000),
        ("3.705 lakh", 370_500),
        ("teen lakh", 300_000),
        ("dhai lakh", 250_000),
        ("तीन लाख", 300_000),
        ("साढ़े तीन लाख", 350_000),
        ("३.७ लाख", 370_000),
        ("दीड लाख", 150_000),
        ("3 lakh 70 thousand", 370_000),
        ("1 crore 20 lakh", 12_000_000),
        ("about 3.5 lakh", 350_000),
        # Ambiguous words keep only stated_as.
        ("3.70", None),
        ("about 3 to 4", None),
        ("3-4 lakh", None),
        ("3 or 4 lakh", None),
        ("3 lakh 70", None),
        ("70 thousand 3 lakh", None),
        ("2 panels and 45k", None),
        ("five", None),
        ("5 kW", None),
        ("5000 watt", None),
        ("1.234567 lakh", None),
        ("", None),
        ("costly", None),
    ],
)
def test_amount_inr_reads_only_the_words_said(words: str, expected: int | None) -> None:
    assert amount_inr(words) == expected


@pytest.mark.parametrize(
    "words,expected",
    [
        ("5 kW", (5, "kW")),
        ("5kw", (5, "kW")),
        ("5  KW", (5, "kW")),
        ("5 k.w.", (5, "kW")),
        ("3.5 kW", (3.5, "kW")),
        ("10 KVA", (10, "kVA")),
        ("5000 watt", (5, "kW")),
        ("1100 VA", (1.1, "kVA")),
        ("five kilowatt", (5, "kW")),
        ("5 kilo watt", (5, "kW")),
        ("paanch kW", (5, "kW")),
        ("5 किलोवाट", (5, "kW")),
        ("5", (5, None)),
        ("3 to 5 kW", (None, None)),
        ("two 5 kW systems", (None, None)),
        ("a big system", (None, None)),
        ("", (None, None)),
    ],
)
def test_system_size_reads_quantity_and_unit(
    words: str, expected: tuple[int | float | None, str | None]
) -> None:
    assert system_size(words) == expected


@pytest.mark.parametrize(
    "words,expected",
    [
        ("one dongle", {Decimal(1)}),
        ("2 dongles", {Decimal(2)}),
        ("seven years", {Decimal(7)}),
        ("पांच साल", {Decimal(5)}),
        ("saade teen", {Decimal("3.5")}),
        ("a dongle", set()),
    ],
)
def test_numbers_in_finds_every_number_said(words: str, expected: set[Decimal]) -> None:
    assert numbers_in(words) == expected


@pytest.mark.parametrize(
    "words,plain,expected",
    [
        ("3.70 lakh", True, True),
        ("Rs 500", True, True),
        ("₹ 900", True, True),
        ("45000", True, True),
        ("45k", True, True),
        ("5 kW", True, False),
        ("5000 watt", True, False),
        ("1500 sq ft roof", True, False),
        ("by 2026", True, False),
        ("send the quotation today", True, False),
        ("PuREPower 5", False, False),
        ("PP 5000", False, False),
        ("PP 5000", True, True),
        ("PP 3 lakh", False, True),
    ],
)
def test_mentions_price(words: str, plain: bool, expected: bool) -> None:
    assert mentions_price(words, plain_numbers=plain) is expected


@pytest.mark.parametrize(
    "words,expected",
    [
        ("3.7 lakh plus GST", "ex_gst"),
        ("3.7 lakh + GST", "ex_gst"),
        ("GST extra", "ex_gst"),
        ("3.7 lakh including GST", "incl_gst"),
        ("inclusive of GST", "incl_gst"),
        ("3.7 lakh", None),
        ("GST", None),
        ("inclusive of GST, transport extra", None),
    ],
)
def test_gst_basis_needs_gst_and_one_clear_cue(words: str, expected: str | None) -> None:
    assert gst_basis(words) == expected
