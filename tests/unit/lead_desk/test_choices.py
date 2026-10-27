"""Seller chip choices (lead_desk/choices.py, owner bug #49): what a seller's languages,
areas and products are picked from, read the way seller matching and rules read them."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from ac_platform.lead_desk import allocation, choices, routing
from ac_platform.lead_desk.journey.templates import TEMPLATES

ROWS: list[choices.Row] = [
    ("Navi Mumbai", "Hindi, English", "Home loan", 5),
    ("navi-mumbai", "hi-mr", "home  loan", 2),
    ("Pune", "Marathi", "Car loan", 3),
    (None, None, None, 4),
    ("  ", "English", "", 1),
    ("Thane", "Konkani and Hindi", None, 1),
]


def _seller(**limits: tuple[str, ...]) -> allocation.RepState:
    return allocation.RepState(
        person_id=uuid4(),
        name="Fictional Seller",
        available=True,
        max_open=None,
        open_leads=0,
        **limits,
    )


def _chips(found: tuple[choices.Choice, ...]) -> list[tuple[str, str, int]]:
    return [(chip.value, chip.key, chip.leads) for chip in found]


def test_spellings_with_one_key_are_one_chip_in_their_most_common_spelling() -> None:
    view = choices.view(ROWS, days=90, industry=None)
    assert view.days == 90 and view.leads == 16
    assert _chips(view.areas) == [
        ("Navi Mumbai", "navi mumbai", 7),
        ("Pune", "pune", 3),
        ("Thane", "thane", 1),
    ]
    assert _chips(view.products) == [("Home loan", "home loan", 7), ("Car loan", "car loan", 3)]
    # Each language a lead names counts once, by its code and its name; "and" is no language.
    assert _chips(view.languages) == [
        ("Hindi", "hi", 8),
        ("English", "en", 6),
        ("Marathi", "mr", 5),
        ("Konkani", "konkani", 1),
    ]
    assert view.more == choices.More()
    assert view.industry is None and view.suggested_products == ()


def test_a_picked_chip_matches_its_own_leads_in_seller_matching_and_in_rules() -> None:
    view = choices.view(ROWS, days=90, industry=None)
    for city, language, interest, _ in ROWS:
        lead = allocation.LeadFacts(language=language, city=city, interest=interest)
        facts = routing.LeadFacts(city=city, language=language, interest=interest)
        for chip in view.areas:
            if city and allocation.key(city) == chip.key:
                assert allocation.checks(lead, _seller(areas=(chip.value,)))[1] is True
                assert routing.FieldIn("city", (chip.value,)).holds(facts)
        for chip in view.products:
            if interest and allocation.key(interest) == chip.key:
                assert allocation.checks(lead, _seller(interests=(chip.value,)))[2] is True
                assert routing.FieldIn("interest", (chip.value,)).holds(facts)
        for chip in view.languages:
            if language and chip.key in allocation.language_codes(language):
                for picked in (chip.value, chip.key):
                    assert allocation.checks(lead, _seller(languages=(picked,)))[0] is True
                    assert routing.FieldIn("language", (picked,)).holds(facts)


def test_sixty_chips_at_most_and_how_many_more() -> None:
    rows: list[choices.Row] = [(f"Fictional Area {n}", None, None, 100 - n) for n in range(65)]
    view = choices.view(rows, days=90, industry=None)
    assert len(view.areas) == 60 and view.more.areas == 5
    assert view.areas[0].value == "Fictional Area 0" and view.areas[-1].leads == 41


def test_the_industry_profile_is_named_and_carries_no_products() -> None:
    profile = TEMPLATES[0]
    view = choices.view([], days=30, industry=profile.id)
    assert view.industry == choices.Industry(id=profile.id, name=profile.name)
    assert view.suggested_products == () and view.leads == 0
    assert choices.view([], days=30, industry="no-such-profile").industry is None


def test_fit_counts_the_leads_a_profile_would_take_with_allocations_own_check() -> None:
    command = choices.FitCommand(languages=["Hindi"], areas=["navi mumbai"], products=[])
    # A lead with no value, and a seller with no limit, aren't limited by that check.
    assert choices.fit(ROWS, command) == choices.FitView(
        days=30,
        leads=16,
        fits=11,
        percent=69,
        by=choices.FitBy(language=12, area=12, product=16),
    )
    assert choices.fit([], choices.FitCommand()).percent == 0


def test_a_fit_takes_at_most_fifty_values_of_eighty_characters() -> None:
    with pytest.raises(ValidationError):
        choices.FitCommand(areas=["x" * 81])
    with pytest.raises(ValidationError):
        choices.FitCommand(products=[f"Fictional {n}" for n in range(51)])
    assert choices.FitCommand(languages=[" Hindi ", " "]).languages == ["Hindi"]


def test_rule_conditions_read_city_interest_and_language_by_the_same_keys() -> None:
    facts = routing.LeadFacts(
        city="Navi-Mumbai", language="Hindi, English", interest="Home  Loan", source="webhook"
    )
    assert routing.FieldIn("city", ("navi mumbai",)).holds(facts)
    assert routing.FieldIn("interest", ("home loan",)).holds(facts)
    assert routing.FieldIn("language", ("Hindi",)).holds(facts)
    assert routing.FieldIn("language", ("en",)).holds(facts)
    assert not routing.FieldIn("language", ("Marathi",)).holds(facts)
    # A rule names an area exactly: "Mumbai" isn't "Navi Mumbai".
    assert not routing.FieldIn("city", ("Mumbai",)).holds(facts)
    assert routing.FieldIn("source", ("WEBHOOK",)).holds(facts)
    assert not routing.FieldIn("city", ("Pune",)).holds(routing.LeadFacts())
