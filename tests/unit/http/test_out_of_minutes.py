"""The upload refusal for want of minutes says what's true (simulation lab, 1 Nov 2026)."""

import pytest

from ac_platform.http.conversation_submissions import out_of_minutes


@pytest.mark.parametrize(
    ("allowance", "organisation", "words"),
    [
        (
            {"allowance_seconds": 0, "committed_seconds": 0, "available_seconds": 0},
            True,
            "Call analysis isn't on for this organisation yet: it has no analysis allowance. "
            "Ask your owner.",
        ),
        (
            {"allowance_seconds": 0, "committed_seconds": 0, "available_seconds": 0},
            False,
            "Call analysis isn't on for your account yet: it has no analysis allowance.",
        ),
        (
            {"allowance_seconds": 600, "committed_seconds": 600, "available_seconds": 0},
            True,
            "This organisation's analysis allowance is used up. "
            "Ask your owner for more call minutes.",
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


@pytest.mark.parametrize("organisation", [True, False])
@pytest.mark.parametrize("granted", [0, 600])
def test_every_answer_names_the_allowance_so_the_phone_waits_for_minutes(organisation, granted):
    """The phone app's contract (sales-xray-apps CaptureRules.refusal, tested there by
    allowanceRefusalHoldsAndRetriesOnceMinutesExist): a 409 whose words contain "allowance"
    holds the call as waiting for minutes and uploads it by itself once minutes exist; any
    other 409 is held for review (Redmi QA on production, 10 Nov 2026)."""
    allowance = {"allowance_seconds": granted, "committed_seconds": granted, "available_seconds": 0}
    assert "allowance" in out_of_minutes(allowance, organisation=organisation).lower()
