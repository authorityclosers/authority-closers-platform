"""The duplicate engine (lead_desk/dupes.py): its normalisers and similarity, the bands with
their reasons, the rule that two leads with different phones and different emails are never
more than a hint, and properties over seeded random leads (symmetric, deterministic, every
pair once, the cap held). Made-up people only."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from ac_platform.lead_desk.dupes import (
    RANK,
    Card,
    company_key,
    find,
    fold_email,
    jaro_winkler,
    last10,
    name_similarity,
    score,
)

T0 = datetime(2026, 10, 25, 10, 0, tzinfo=UTC)


def card(n: int, **fields: object) -> Card:
    return Card(lead_id=UUID(int=n), **fields)  # type: ignore[arg-type]


def test_jaro_winkler_known_values() -> None:
    assert jaro_winkler("martha", "marhta") == pytest.approx(0.961, abs=0.001)
    assert jaro_winkler("dwayne", "duane") == pytest.approx(0.84, abs=0.001)
    assert jaro_winkler("same", "same") == 1.0
    assert jaro_winkler("", "x") == 0.0
    assert jaro_winkler("abc", "xyz") == 0.0


def test_emails_fold_typos_www_and_gmail_dots() -> None:
    assert fold_email("Www.Ravi@GAMIL.com") == "ravi@gmail.com"
    assert fold_email("r.a.v.i+leads@gmail.com") == "ravi@gmail.com"
    assert fold_email("asha@yahoo.co") == "asha@yahoo.com"
    # Dots matter outside Gmail.
    assert fold_email("a.sha@example.com") == "a.sha@example.com"
    assert fold_email("not an email") is None
    assert last10("+91 98760 12345") == "9876012345"
    assert last10("12345") is None
    assert company_key("Sample Traders Pvt. Ltd.") == company_key("sample traders private limited")


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Mohammad Imran", "Muhammed Imran"),
        ("Sanjay Patil", "Sanjai Patil"),
        ("Shubham Kulkarni", "Subham Kulkarni"),
        ("Dr. Asha Rao", "Asha Rao"),
        ("Kulkarni Shubham", "Shubham Kulkarni"),
    ],
)
def test_romanised_spellings_meet(first: str, second: str) -> None:
    assert name_similarity(first, second) >= 0.92


def test_bands_and_reasons() -> None:
    same_phone = score(
        card(1, name="Asha Example", phones=("+919876012345",)),
        card(2, name="A Example", phones=("+919876012345",)),
    )
    assert same_phone.band == "certain" and "same phone number" in same_phone.reasons

    # The same last ten digits under another country code, and the same name.
    last_ten = score(
        card(1, name="Ravi Sample", phones=("+19876012345",)),
        card(2, name="Ravi Sample", phones=("+919876012345",)),
    )
    assert last_ten.band == "probable"
    assert last_ten.reasons[:2] == ("same last 10 digits of the phone", "same name")

    typo = score(
        card(1, name="Neha Demo", emails=("neha.demo@gamil.com",)),
        card(2, name="Neha Demo", emails=("nehademo@gmail.com",)),
    )
    assert typo.band == "probable" and "same email apart from a typo" in typo.reasons

    # Different phones and different emails: two people, whatever the name says.
    two = score(
        card(1, name="Rahul Demo", phones=("+919876012345",), emails=("rahul@example.com",)),
        card(2, name="Rahul Demo", phones=("+919876099999",), emails=("rd@example.org",)),
    )
    assert two.band in (None, "possible")
    assert "different phones" in two.against and "different emails" in two.against

    # Name, company, city and the same day, no contact details: probable.
    company = score(
        card(1, name="Kavya Example", company="Example Solar Pvt Ltd", city="pune", received_at=T0),
        card(
            2,
            name="Kavya Example",
            company="Example Solar",
            city="Pune Maharashtra",
            received_at=T0 + timedelta(hours=3),
        ),
    )
    assert company.band == "probable"
    assert set(company.reasons) >= {
        "same name",
        "same company",
        "same city",
        "came in the same day",
    }

    nothing = score(card(1, name="Asha Example"), card(2, name="Vikram Sample"))
    assert nothing.band is None


def test_find_blocks_reports_each_pair_once_and_the_likeliest_first() -> None:
    cards = [
        card(1, name="Neha Demo", emails=("neha.demo@gamil.com",)),
        card(2, name="Neha Demo", emails=("nehademo@gmail.com",), phones=("+919876011111",)),
        card(3, name="Ravi Sample", phones=("+919876012345",)),
        card(4, name="Ravi Sample", phones=("+919876012345",)),
        card(5, name="Pooja Example", phones=("+919876033333",)),
    ]
    found = find(cards)
    assert [(p.first.int, p.second.int, p.band) for p in found] == [
        (3, 4, "certain"),
        (1, 2, "probable"),
    ]
    assert [p.band for p in find(cards, minimum="certain")] == ["certain"]


FIRST = ["Asha", "Ravi", "Neha", "Arjun", "Kavya", "Rahul", "Pooja", "Imran", "Sanjay", "Lata"]
LAST = ["Example", "Sample", "Demo", "Patil", "Kulkarni", "Rao"]


def random_cards(rng: random.Random, count: int) -> list[Card]:
    cards = []
    for n in range(1, count + 1):
        phones = tuple(f"+9198760{rng.randint(10000, 10040)}" for _ in range(rng.randint(0, 2)))
        domains = ["gmail.com", "gamil.com", "example.com"]
        emails = tuple(
            f"{rng.choice(FIRST).lower()}{rng.randint(1, 4)}@{rng.choice(domains)}"
            for _ in range(rng.randint(0, 1))
        )
        cards.append(
            card(
                n,
                name=f"{rng.choice(FIRST)} {rng.choice(LAST)}" if rng.random() < 0.9 else None,
                phones=phones,
                emails=emails,
                city=rng.choice(["Pune", "pune", "Nagpur", None]),
                received_at=T0 + timedelta(hours=rng.randint(0, 72)),
            )
        )
    return cards


@pytest.mark.parametrize("seed", range(20))
def test_properties_over_random_leads(seed: int) -> None:
    rng = random.Random(seed)  # noqa: S311 - seeded test data, not security
    cards = random_cards(rng, 40)
    found = find(cards)
    # Deterministic, each pair once, never a lead with itself, likeliest first.
    assert found == find(cards)
    keys = [(pair.first, pair.second) for pair in found]
    assert len(keys) == len(set(keys)) and all(a < b for a, b in keys)
    assert [pair.score for pair in found] == sorted((pair.score for pair in found), reverse=True)
    by_id = {c.lead_id: c for c in cards}
    for pair in found:
        a, b = by_id[pair.first], by_id[pair.second]
        # Symmetric.
        assert score(a, b) == score(b, a)
        # Different phones and different emails: never above a hint.
        if "different phones" in pair.against and "different emails" in pair.against:
            assert pair.band == "possible"
        assert pair.band is not None and RANK[pair.band] >= 1 and pair.reasons


def test_two_organisations_are_never_compared() -> None:
    first, second = UUID(int=101), UUID(int=102)
    same = {"name": "Asha Example", "phones": ("+919876012345",)}
    with pytest.raises(ValueError, match="one organisation"):
        find([card(1, tenant_id=first, **same), card(2, tenant_id=second, **same)])
    assert len(find([card(1, tenant_id=first, **same), card(2, tenant_id=first, **same)])) == 1
