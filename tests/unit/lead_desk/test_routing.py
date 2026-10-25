"""Routing rules (lead_desk/routing.py): the owner's "more than X to one seller, under Y to
another", caps, round-robin inside a group, the first matching rule winning, a plain reason on
every decision, and properties over seeded random leads and teams. Made-up people only."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from uuid import UUID

from ac_platform.lead_desk.facets import Band, value_band
from ac_platform.lead_desk.routing import (
    AnswerIn,
    FieldIn,
    LeadFacts,
    Rule,
    Seat,
    ValueIs,
    decide,
    matches,
)

T0 = datetime(2026, 10, 25, 10, 0, tzinfo=UTC)
ASHA, RAVI, NEHA = UUID(int=1), UUID(int=2), UUID(int=3)
HIGH = Rule((ValueIs("at_least", low=100_000),), (ASHA,))
LOW = Rule((ValueIs("below", high=60_000),), (RAVI,))


def seat(person: UUID, name: str, **extra: object) -> Seat:
    fields: dict[str, object] = {"available": True, "open_leads": 0, "cap": 50, **extra}
    return Seat(person, name, **fields)  # type: ignore[arg-type]


TEAM = (seat(ASHA, "Asha"), seat(RAVI, "Ravi"), seat(NEHA, "Neha"))


def test_acceptance_value_rules_name_the_rule() -> None:
    high = decide(LeadFacts(value=value_band("₹1,00,000+")), (HIGH, LOW), TEAM)
    assert high.person_id == ASHA and high.rule == 1
    assert high.why == "Value ₹1,00,000+ ≥ ₹1,00,000: Asha (rule 1)"
    low = decide(LeadFacts(value=value_band("₹15,000 – ₹30,000")), (HIGH, LOW), TEAM)
    assert low.person_id == RAVI and low.rule == 2
    assert low.why == "Value ₹15,000 – ₹30,000 < ₹60,000: Ravi (rule 2)"


def test_a_band_across_the_line_meets_neither_rule() -> None:
    middle = decide(LeadFacts(value=value_band("₹60,000 – ₹1,00,000")), (HIGH, LOW), TEAM)
    assert middle.person_id is None and middle.rule is None
    assert "lead rules" in middle.why
    assert decide(LeadFacts(), (HIGH, LOW), TEAM).person_id is None


def test_at_the_cap_the_lead_falls_through_and_says_so() -> None:
    full = (seat(ASHA, "Asha", open_leads=50), seat(RAVI, "Ravi"))
    decision = decide(LeadFacts(value=Band(200_000, None)), (HIGH, LOW), full)
    assert decision.person_id is None
    assert decision.why == "Rule 1: Asha away or at their limit, given by the lead rules"
    away = (seat(ASHA, "Asha", available=False), seat(RAVI, "Ravi"))
    assert decide(LeadFacts(value=Band(200_000, None)), (HIGH,), away).person_id is None
    unlimited = (seat(ASHA, "Asha", open_leads=500, cap=None),)
    assert decide(LeadFacts(value=Band(200_000, None)), (HIGH,), unlimited).person_id == ASHA


def test_a_group_takes_turns() -> None:
    group = Rule((FieldIn("city", ("Pune",)),), (ASHA, RAVI))
    seats = (
        seat(ASHA, "Asha", last_given_at=T0),
        seat(RAVI, "Ravi", last_given_at=T0 - timedelta(hours=1)),
    )
    assert decide(LeadFacts(city="pune"), (group,), seats).person_id == RAVI
    never = (seat(ASHA, "Asha"), seat(RAVI, "Ravi"))
    assert decide(LeadFacts(city="Pune"), (group,), never).person_id == ASHA


def test_answers_and_fields_match_by_their_words() -> None:
    rule = Rule(
        (
            AnswerIn("what_do_you_currently_do", ("Business owner / startup",)),
            FieldIn("language", ("Marathi", "Hindi")),
        ),
        (NEHA,),
    )
    facts = LeadFacts(
        answers={"what_do_you_currently_do": "business  owner / startup"}, language="Marathi"
    )
    assert matches(rule, facts)
    decided = decide(facts, (rule,), TEAM)
    assert decided.person_id == NEHA
    assert decided.why == '"business  owner / startup"; Marathi: Neha (rule 1)'
    assert not matches(rule, LeadFacts(answers=facts.answers, language="Tamil"))
    assert not matches(Rule((), (NEHA,)), facts)


def test_properties_over_random_leads_and_teams() -> None:
    rng = random.Random(20261025)  # noqa: S311 - seeded test data, not security
    people = [UUID(int=n) for n in range(1, 7)]
    for _ in range(500):
        seats = tuple(
            seat(
                person,
                f"Seller {person.int}",
                available=rng.random() > 0.2,
                open_leads=rng.randint(0, 6),
                cap=rng.choice([None, 3, 5, 8]),
                last_given_at=rng.choice([None, T0 - timedelta(minutes=rng.randint(0, 999))]),
            )
            for person in people
        )
        rules = tuple(
            Rule(
                (
                    ValueIs("at_least", low=rng.choice([20_000, 60_000, 100_000]))
                    if rng.random() < 0.5
                    else ValueIs("below", high=rng.choice([20_000, 60_000, 100_000])),
                ),
                tuple(rng.sample(people, rng.randint(1, 3))),
            )
            for _ in range(rng.randint(0, 4))
        )
        low = rng.choice([None, 5_000, 40_000, 90_000, 150_000])
        facts = LeadFacts(
            value=None if low is None else Band(low, rng.choice([None, low, low + 30_000]))
        )
        decision = decide(facts, rules, seats)
        # Deterministic.
        assert decide(facts, rules, seats) == decision
        by_person = {item.person_id: item for item in seats}
        if decision.person_id is None:
            # Nobody in any matching rule had room.
            for rule in rules:
                if matches(rule, facts):
                    assert not any(by_person[p].has_room for p in rule.people)
            continue
        assert decision.rule is not None
        chosen = rules[decision.rule - 1]
        # Never over a cap, never someone away, and someone in the rule.
        assert by_person[decision.person_id].has_room
        assert decision.person_id in chosen.people and matches(chosen, facts)
        # The first rule that could give it out did.
        for earlier in rules[: decision.rule - 1]:
            if matches(earlier, facts):
                assert not any(by_person[p].has_room for p in earlier.people)
        # No value meets no value rule.
        if facts.value is None:
            raise AssertionError("a lead with no value met a value rule")
