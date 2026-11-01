"""The upload refusal for want of minutes says what's true (simulation lab, 1 Nov 2026)."""

import pytest

from ac_platform.http.conversation_submissions import out_of_minutes


@pytest.mark.parametrize(
    ("allowance", "organisation", "words"),
    [
        (
            {"allowance_seconds": 0, "committed_seconds": 0, "available_seconds": 0},
            True,
            "Call analysis isn't on for this organisation yet. Ask your owner.",
        ),
        (
            {"allowance_seconds": 0, "committed_seconds": 0, "available_seconds": 0},
            False,
            "Call analysis isn't on for your account yet.",
        ),
        (
            {"allowance_seconds": 600, "committed_seconds": 600, "available_seconds": 0},
            True,
            "This organisation's call minutes are used up. Ask your owner.",
        ),
        (
            {"allowance_seconds": 3600, "committed_seconds": 3600, "available_seconds": 0},
            False,
            "Your current free call allowance has been used.",
        ),
    ],
)
def test_out_of_minutes_says_what_is_true(allowance, organisation, words):
    assert out_of_minutes(allowance, organisation=organisation) == words
    assert "₹" not in words and "price" not in words.lower()
