"""Facets and value bands (lead_desk/facets.py): money as people write it in India, the
answers that are choices, and what is never an answer. Made-up answers only."""

from __future__ import annotations

import pytest

from ac_platform.lead_desk.facets import Band, band_words, facets, rupees, value_band


@pytest.mark.parametrize(
    ("text", "band"),
    [
        ("₹60,000 – ₹1,00,000", Band(60_000, 100_000)),
        ("₹1,00,000+", Band(100_000, None)),
        ("Under ₹15,000", Band(None, 15_000)),
        ("Less than 15k", Band(None, 15_000)),
        ("15k-30k", Band(15_000, 30_000)),
        ("15-30k", Band(15_000, 30_000)),
        ("1-1.5 lakh", Band(100_000, 150_000)),
        ("50,000 to 1 lakh", Band(50_000, 100_000)),
        ("Rs. 2L+", Band(200_000, None)),
        ("Above 5 lakhs", Band(500_000, None)),
        ("up to 50000", Band(None, 50_000)),
        ("1 crore", Band(10_000_000, 10_000_000)),
        ("INR 25000", Band(25_000, 25_000)),
        ("₹15, 000 – ₹30, 000", Band(15_000, 30_000)),
        ("₹30,000 - ₹15,000", Band(15_000, 30_000)),
    ],
)
def test_value_bands(text: str, band: Band) -> None:
    assert value_band(text) == band


@pytest.mark.parametrize("text", ["Not sure", "", "Business owner / startup", None, True])
def test_no_amount_no_band(text: object) -> None:
    assert value_band(text) is None


def test_mid_and_words() -> None:
    assert Band(60_000, 100_000).mid == 80_000
    assert Band(100_000, None).mid == 100_000
    assert rupees(100_000) == "₹1,00,000" and rupees(999) == "₹999"
    assert rupees(12_345_678) == "₹1,23,45,678"
    assert band_words(Band(100_000, None)) == "₹1,00,000+"
    assert band_words(Band(None, 15_000)) == "under ₹15,000"
    assert band_words(Band(60_000, 100_000)) == "₹60,000 – ₹1,00,000"


def test_facets_are_short_answers_by_question() -> None:
    payload = {
        "full_name": "Fictional Person",
        "phone_number": "+91 98760 00000",
        "email": "fictional@example.com",
        "leadgen_id": "1234567890",
        "created_time": "2026-10-25T10:00:00+0000",
        "What do you currently do?": "Business owner / startup",
        "what_is_your_budget?": "₹60,000 – ₹1,00,000",
        "Tell us about your goals": "x" * 200,
        "Alternate number": "98760 00001",
        "_internal": "kept out",
        "campaign_name": "Fictional campaign",
        "Preferred batch": "Weekend",
    }
    found = {facet.key: facet for facet in facets(payload)}
    # The campaign is the lead's interest (capture.ALIASES): a field, not an answer.
    assert set(found) == {"what_do_you_currently_do", "what_is_your_budget", "preferred_batch"}
    assert found["what_do_you_currently_do"].label == "What do you currently do?"
    assert found["what_is_your_budget"].value == "₹60,000 – ₹1,00,000"


def test_meta_field_data_answers_are_facets() -> None:
    payload = {
        "field_data": [
            {"name": "full_name", "values": ["Fictional Person"]},
            {"name": "monthly_income", "values": ["₹1,00,000+"]},
        ]
    }
    assert [(f.key, f.value) for f in facets(payload)] == [("monthly_income", "₹1,00,000+")]
