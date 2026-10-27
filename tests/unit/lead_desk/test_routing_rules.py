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
