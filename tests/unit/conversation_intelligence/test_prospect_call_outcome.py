"""No implicit outcome, contact, stage, currency conversion or AI provenance."""

from datetime import date, datetime

import pytest

from ac_platform.conversation_intelligence.prospect_call_outcome import (
    DealValue,
    HumanOutcome,
    OutcomeValidationError,
)


@pytest.mark.parametrize(
    "payload",
    [
        {"outcome": "won"},
        {"outcome": "no_decision"},
        {"outcome": "lost", "lost_reason": "  Chose another option.  "},
        {"outcome": "follow_up", "follow_up_on": "2026-10-12"},
        {
            "outcome": "won",
            "deal_value": {"amount": "125000.0000", "currency_code": "INR"},
        },
        {"outcome": "no_decision", "deal_value": {"amount": "0", "currency_code": "USD"}},
    ],
)
def test_human_values_round_trip_without_conversion(payload: dict[str, object]) -> None:
    value = HumanOutcome.parse(payload)
    assert HumanOutcome.parse(value.json()) == value
    for key, supplied in payload.items():
        assert value.json()[key] == supplied


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"outcome": "unknown"},
        {"outcome": True},
        {"outcome": ["won"]},
        {"outcome": "Won"},
        {"outcome": "lost"},
        {"outcome": "lost", "lost_reason": " "},
        {"outcome": "lost", "lost_reason": "x" * 1001},
        {"outcome": "lost", "lost_reason": "private\x00reason"},
        {"outcome": "won", "lost_reason": "private reason"},
        {"outcome": "follow_up"},
        {"outcome": "follow_up", "follow_up_on": "2026-02-30"},
        {"outcome": "follow_up", "follow_up_on": "20261012"},
        {"outcome": "follow_up", "follow_up_on": "2026-10-12T10:00:00Z"},
        {"outcome": "follow_up", "follow_up_on": 20261012},
        {"outcome": "no_decision", "follow_up_on": "2026-10-12"},
        {"outcome": "won", "basis": "heard_in_call"},
        {"outcome": "won", "created_by": "some other person"},
        {"outcome": "won", "stage": "qualified"},
        {"outcome": "won", "deal_value": {"amount": "10"}},
        {"outcome": "won", "deal_value": {"amount": "10", "currency_code": "INR", "scale": "lakh"}},
    ],
)
def test_invalid_shapes_never_create_an_outcome(payload: object) -> None:
    with pytest.raises(OutcomeValidationError) as caught:
        HumanOutcome.parse(payload)
    assert "private" not in str(caught.value)


@pytest.mark.parametrize(
    "amount",
    [
        10,
        True,
        10.5,
        "NaN",
        "Infinity",
        "-1",
        "1e5",
        "1,000",
        " 10",
        "01",
        "1.00001",
        "10000000000000000",
    ],
)
def test_deal_values_are_exact_nonnegative_decimal_strings(amount: object) -> None:
    with pytest.raises(OutcomeValidationError):
        HumanOutcome.parse(
            {"outcome": "won", "deal_value": {"amount": amount, "currency_code": "INR"}}
        )


@pytest.mark.parametrize("currency", [None, 1, "inr", "₹", "INR ", "INRU"])
def test_currency_is_explicit_and_not_guessed(currency: object) -> None:
    with pytest.raises(OutcomeValidationError):
        HumanOutcome.parse(
            {"outcome": "won", "deal_value": {"amount": "10", "currency_code": currency}}
        )


def test_direct_construction_has_the_same_guards() -> None:
    with pytest.raises(OutcomeValidationError):
        HumanOutcome("follow_up", follow_up_on=datetime(2026, 10, 12))
    assert (
        HumanOutcome("follow_up", follow_up_on=date(2026, 10, 12)).json()["follow_up_on"]
        == "2026-10-12"
    )
    assert DealValue("10.0000", "INR").json()["amount"] == "10.0000"
