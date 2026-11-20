"""Routing rules as saved (lead_desk/routing_rules.py): what a condition must say, how saved
rules become routing.py's rules, and what a lead's facts are. Made-up people only."""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from ac_platform.lead_desk import routing, routing_rules
from ac_platform.lead_desk.facets import Band

ASHA = UUID(int=1)


@pytest.mark.parametrize(
    "condition",
    [
        {"field": "value", "op": "at_least"},
        {"field": "value", "op": "between", "low": 200, "high": 100},
        {"field": "city", "values": ["  "]},
        {"field": "answer", "values": ["Yes"]},
        {"field": "source", "values": ["carrier pigeon"]},
    ],
)
def test_a_condition_says_what_it_needs(condition: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        routing_rules.Condition.model_validate(condition)


def test_saved_rules_become_routing_rules_and_switched_off_ones_drop_out() -> None:
    rules = [
        routing_rules.Rule.model_validate(
            {
                "name": "Big budgets",
                "when": [
                    {"field": "value", "op": "at_least", "low": 100000},
                    {"field": "answer", "key": "role", "values": ["Owner"]},
                    {"field": "city", "values": [" Pune "]},
                ],
                "give_to": [str(ASHA)],
            }
        ),
        routing_rules.Rule.model_validate(
            {
                "enabled": False,
                "when": [{"field": "language", "values": ["Hindi"]}],
                "give_to": [str(ASHA)],
            }
        ),
    ]
    [(saved, rule)] = routing_rules.pure(rules)
    assert saved.name == "Big budgets"
    assert rule.people == (ASHA,)
    assert rule.conditions == (
        routing.ValueIs("at_least", low=100000),
        routing.AnswerIn("role", ("Owner",)),
        routing.FieldIn("city", ("Pune",)),
    )


def test_a_leads_facts_read_its_value_answer_and_google_ads() -> None:
    facts = routing_rules.facts(
        source="webhook",
        source_label="Google Ads lead form",
        city="Pune",
        language=None,
        interest=None,
        payload={"budget": "₹60,000 – ₹1,00,000", "role": "Owner"},
        value_answer="budget",
    )
    assert facts.source == "google_ads"
    assert facts.value == Band(60_000, 100_000)
    assert facts.answers["role"] == "Owner"
    plain = routing_rules.facts(
        source="webhook",
        source_label="Fictional website",
        city=None,
        language=None,
        interest=None,
        payload={},
        value_answer="budget",
    )
    assert plain.source == "webhook" and plain.value is None


def test_a_split_rule_needs_shares_that_add_up() -> None:
    people = [str(UUID(int=11)), str(UUID(int=12)), str(UUID(int=13))]
    rule = routing_rules.Rule.model_validate(
        {"id": "wl-split", "name": "Wise Life split", "give_to": people, "shares": [20, 40, 40]}
    )
    assert rule.when == () and rule.shares == (20, 40, 40)
    ((_, made),) = routing_rules.pure((rule,))
    assert made.every and made.key == "wl-split" and made.shares == (20, 40, 40)
    config = {routing_rules.KEY: [rule.model_dump(mode="json")]}
    assert routing_rules.split_keys(config) == ("wl-split",)
    for bad in ([20, 40], [20, 40, 30], [120, -10, -10]):
        with pytest.raises(ValidationError):
            routing_rules.Rule.model_validate({"give_to": people, "shares": bad})
    with pytest.raises(ValidationError):
        routing_rules.Rule.model_validate({"give_to": [people[0], people[0]], "shares": [50, 50]})
    # A plain group with no conditions is for every lead, taking turns: no split to count.
    turns = routing_rules.Rule.model_validate({"id": "t", "give_to": people})
    assert routing_rules.split_keys({routing_rules.KEY: [turns.model_dump(mode="json")]}) == ()
    decided = routing_rules.decide(
        config,
        routing.LeadFacts(),
        tuple(routing.Seat(UUID(p), f"P{i}", True, 0, None) for i, p in enumerate(people)),
        {"wl-split": {}},
    )
    assert decided is not None and decided[0].person_id == UUID(people[1])
    assert decided[0].split == "wl-split" and decided[1] == "Wise Life split"
