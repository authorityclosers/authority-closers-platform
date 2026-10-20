"""Lead stages to Google Ads (offline conversion import, enhanced conversions for leads):
which stages Google hears, what one upload says, and how Google's answers are read."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from ac_platform.lead_desk.journey import mapping
from ac_platform.lead_desk.journey.model import Journey, default_journey, from_template
from ac_platform.lead_desk.journey.providers import google_ads, sha256

LEAD = UUID("00000000-0000-4000-8000-0000000000aa")


def journey(template: str) -> Journey:
    return Journey(1, template, from_template(template, default_journey(), {}))


def lead(**extra: Any) -> Any:
    values = {"id": LEAD, "payload": {}, "email": None, "phone": None, **extra}
    return SimpleNamespace(**values)


def test_google_hears_the_moments_that_matter_by_meaning() -> None:
    names = mapping.suggestions("google_ads", journey("real_estate"))
    assert names["new"] is None  # Google counts the form itself
    assert names["contacted"] is None  # a first talk isn't a qualified lead yet
    assert names["site_visit_booked"] == "booked_appointment"
    # One stage per Google moment: the visit that happened adds nothing new.
    assert names["site_visit_done"] is None
    assert names["booked"] == "converted_lead"
    assert names["lost"] is None and names["not_connected"] is None
    b2b = mapping.suggestions("google_ads", journey("b2b_services"))
    assert b2b["qualified"] == "qualified_lead"
    insurance = mapping.suggestions("google_ads", journey("insurance"))
    assert insurance["quote_shared"] == "requested_quote"
    assert insurance["policy_issued"] == "converted_lead"


def test_only_googles_own_moments_can_be_confirmed() -> None:
    plan = journey("real_estate")
    assert mapping.clean_events("google_ads", plan, {"booked": "converted_lead"}) == {
        "booked": "converted_lead"
    }
    try:
        mapping.clean_events("google_ads", plan, {"booked": "Booked"})
    except ValueError as error:
        assert "Google Ads" in str(error)
    else:
        raise AssertionError("a free name was taken for Google")


def test_a_lead_goes_with_its_click_id_and_or_hashed_contact() -> None:
    assert google_ads.identity(lead()) is None
    from_form = google_ads.identity(lead(payload={"gcl_id": "Cj0KCQjwFictional123"}))
    assert from_form == {"lead_ref": str(LEAD), "gclid": "Cj0KCQjwFictional123"}
    by_contact = google_ads.identity(lead(email=" Asha@Example.test ", phone="+91 98765 43210"))
    assert by_contact is not None
    assert by_contact["em"] == sha256("asha@example.test")
    assert by_contact["ph"] == sha256("+919876543210")


def test_one_upload_says_only_what_google_matches_on() -> None:
    settings = SimpleNamespace(
        extra={"actions": {"converted_lead": "customers/1234567890/conversionActions/55"}}
    )
    who = {"lead_ref": str(LEAD), "gclid": "Cj0KCQjwFictional123", "em": "e" * 64}
    body = google_ads.body(
        who,
        event_name="converted_lead",
        at=datetime(2026, 10, 20, 9, 30, tzinfo=UTC),
        settings=settings,
    )
    assert body == {
        "conversionAction": "customers/1234567890/conversionActions/55",
        "conversionDateTime": "2026-10-20 09:30:00+00:00",
        "orderId": body["orderId"],
        "gclid": "Cj0KCQjwFictional123",
        "userIdentifiers": [{"hashedEmail": "e" * 64, "userIdentifierSource": "FIRST_PARTY"}],
    }
    assert len(body["orderId"]) == 40


def test_googles_answers() -> None:
    assert google_ads.read_answer(200, {"results": [{}]}, 5).delivered
    terms = google_ads.read_answer(
        200,
        {"partialFailureError": {"message": "CUSTOMER_NOT_ACCEPTED_CUSTOMER_DATA_TERMS"}},
        5,
    )
    assert (terms.delivered, terms.wait) == (False, "customer")
    assert terms.error_code == "google_customer_not_accepted_customer_data_terms"
    recent = google_ads.read_answer(
        200, {"partialFailureError": {"message": "TOO_RECENT_CONVERSION_ACTION"}}, 5
    )
    assert recent.wait == "retry"
    bad = google_ads.read_answer(200, {"partialFailureError": {"message": "UNPARSEABLE_GCLID"}}, 5)
    assert (bad.wait, bad.error_code) == ("never", "google_unparseable_gclid")
    assert google_ads.read_answer(503, {}, 5).wait == "retry"
    assert google_ads.read_answer(401, {}, 5).wait == "customer"
