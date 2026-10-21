"""Usage per person and at daily reference rates (orchestrator decisions, 20 Oct 2026).

People are pseudonyms, named only for this Admin's own environment; organisation names come
only from there too; provider costs move to each day's ECB rate, rupee amounts stay rupees.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from ac_platform.conversation_intelligence.cost_metrics import (
    FX,
    Scope,
    at_daily_rates,
    build_metrics,
    parse_export,
)
from tests.unit.conversation_intelligence.test_cost_metrics import NOW, _call, _document, _steps

ASHA = "p_0123456789abcdef"
RAVI = "p_fedcba9876543210"
ORG = "8c1f2e4a-1111-4222-8333-944455556666"


def _people_document() -> dict[str, Any]:
    document = _document()
    document["companies"] = [{"id": ORG, "kind": "organisation"}]
    document["calls"] = [
        _call("call-asha", company=ORG, person=ASHA),
        _call("call-ravi", company=ORG, person=RAVI, hours_ago=8),
        _call("call-none", company=ORG, person="not-a-pseudonym", hours_ago=9),
    ]
    steps = _steps("call-asha") + _steps("call-ravi", hours_ago=8)
    steps += _steps("call-none", hours_ago=9)
    for step in steps:
        step["company"] = ORG
    document["steps"] = steps
    document["pointer_reviews"] = []
    document["ai_work"] = [
        {
            "stage": "AR",
            "call": None,
            "company": ORG,
            "person": RAVI,
            "provider": "gemini",
            "model": "gemini-3.8-flash",
            "status": "sent",
            "trigger": "auto",
            "input_tokens": 4000,
            "output_tokens": 400,
            "cost_inr": None,
            "at": NOW.isoformat(),
        }
    ]
    return document


def _scope(**extra: Any) -> Scope:
    return Scope(now=NOW, days=30, environment="all", tests=False, **extra)


def test_steps_belong_to_their_calls_person_and_bad_pseudonyms_are_dropped() -> None:
    export = parse_export("staging", _people_document())
    people = {call.id: call.person for call in export.calls}
    assert people == {"call-asha": ASHA, "call-ravi": RAVI, "call-none": None}
    assert {step.person for step in export.steps if step.call == "call-asha"} == {ASHA}
    (reply,) = [step for step in export.steps if step.stage == "AR"]
    assert reply.person == RAVI


def test_people_are_offered_by_spend_and_one_person_narrows_everything() -> None:
    export = parse_export("staging", _people_document())
    whole = build_metrics([export], _scope())
    people = whole["choices"]["people"]
    assert [row["id"] for row in people] == [RAVI, ASHA]  # Ravi also has an AI reply
    assert all(row["name"] is None and row["environment"] == "staging" for row in people)
    assert whole["choices"]["people_available"] == ["staging"]

    only = build_metrics([export], _scope(person=ASHA))
    assert only["filters"]["person"] == ASHA
    assert {row["id"] for row in only["calls"]["rows"]} == {"call-asha"}
    assert only["overview"]["spend_window"] < whole["overview"]["spend_window"]

    export.people = {ASHA: "Asha (fictional)"}
    named = build_metrics([export], _scope())
    assert next(r for r in named["choices"]["people"] if r["id"] == ASHA)["name"] == (
        "Asha (fictional)"
    )


def test_an_unnamed_organisation_shows_where_its_name_lives() -> None:
    export = parse_export("staging", _people_document())
    rows = build_metrics([export], _scope())["choices"]["companies"]
    assert rows[0]["id"] == ORG and rows[0]["name"] == "Organisation 8c1f2e4a"
    export.companies[ORG]["name"] = "Fictional Solar Co"  # this environment's live name
    rows = build_metrics([export], _scope())["choices"]["companies"]
    assert rows[0]["name"] == "Fictional Solar Co"


def test_provider_costs_move_to_each_days_rate_and_dollars_stay_exact() -> None:
    export = parse_export("staging", _people_document())
    rates = {date(2026, 10, 1): Decimal("88.0000"), date(2026, 10, 19): Decimal("90.0000")}
    moved, fx = at_daily_rates([export], rates)
    before = sum(step.paise or 0 for step in export.steps)
    after = sum(step.paise or 0 for step in moved[0].steps)
    # Every step here is on 19 Oct (India time): 90 rupees a dollar instead of 100.
    assert abs(after - before * 0.9) <= len(export.steps)
    assert fx["mode"] == "daily" and fx["latest"] == {"day": "2026-10-19", "usd_to_inr": 90.0}
    assert abs(fx["usd_to_inr"] - 90.0) < 0.05 and fx["planning_usd_to_inr"] == 100.0
    assert fx["unrated_steps"] == 0

    # A day before the first stored rate keeps the planning rate, and is counted.
    _, early = at_daily_rates([export], {date(2026, 10, 20): Decimal("91")})
    assert early["unrated_steps"] == len([s for s in export.steps if s.paise is not None])

    # No rates at all: the planning rate, unchanged.
    same, planning = at_daily_rates([export], {})
    assert same[0] is export and planning == FX
