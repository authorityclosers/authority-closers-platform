"""Lead stages to LinkedIn, TikTok and Microsoft Advertising: matches by meaning, what one
event says, how each platform's answers are read, and connections sealed per
organisation. Fictional businesses and ids only."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import UUID

from ac_platform.lead_desk.journey import mapping
from ac_platform.lead_desk.journey.model import Journey, default_journey, from_template
from ac_platform.lead_desk.journey.providers import linkedin, microsoft_ads, oauth, sha256, tiktok

ORG = UUID("00000000-0000-4000-8000-0000000000b1")
OTHER = UUID("00000000-0000-4000-8000-0000000000b2")
PERSON = UUID("00000000-0000-4000-8000-0000000000c1")
LEAD = UUID("00000000-0000-4000-8000-0000000000d1")
AT = datetime(2026, 10, 20, 9, 30, tzinfo=UTC)
KEY = base64.urlsafe_b64encode(b"k" * 32).decode().rstrip("=")
ENV = {
    "AC_LINKEDIN_CLIENT_ID": "fictional-li-client",
    "AC_LINKEDIN_CLIENT_SECRET": "fictional-li-secret",
    "AC_TIKTOK_APP_ID": "7000000000000000001",
    "AC_TIKTOK_APP_SECRET": "fictional-tt-secret",
    "AC_MICROSOFT_ADS_CLIENT_ID": "00000000-0000-4000-8000-00000000abcd",
    "AC_MICROSOFT_ADS_CLIENT_SECRET": "fictional-ms-secret",
    "AC_MICROSOFT_ADS_DEVELOPER_TOKEN": "fictional-ms-token",
    "AC_MICROSOFT_ADS_SANDBOX": "1",
    "AC_LEAD_DESK_TOKEN_KEY": KEY,
}


def plan(template: str) -> Journey:
    return Journey(1, template, from_template(template, default_journey(), {}))


def lead(**extra: Any) -> Any:
    return SimpleNamespace(
        **{"id": LEAD, "payload": {}, "email": None, "phone": None, "source": "webhook", **extra}
    )


def test_every_platform_hears_the_moments_that_matter() -> None:
    real_estate = plan("real_estate")
    li = mapping.suggestions("linkedin", real_estate)
    assert li["site_visit_booked"] == "book_appointment" and li["booked"] == "purchase"
    assert li["new"] is None and li["lost"] is None
    ms = mapping.suggestions("microsoft_ads", real_estate)
    assert ms["site_visit_booked"] == "booked_meeting" and ms["booked"] == "customer"
    tt = mapping.suggestions("tiktok", real_estate)
    # TikTok, like Meta, hears every stage by name.
    assert tt["new"] == "Lead" and tt["site_visit_done"] == "Site visit done"
    assert tt["not_connected"] is None


def test_a_lead_goes_only_with_what_each_platform_matches_on() -> None:
    plain = lead()
    assert linkedin.identity(plain) is None
    assert microsoft_ads.identity(plain) is None
    assert tiktok.identity(plain) is None
    clicked = lead(
        email="ravi@example.test",
        payload={
            "li_fat_id": "li-Fictional-123",
            "msclkid": "msFictional1234",
            "ttclid": "E.C.P.fict1234",
        },
    )
    assert linkedin.identity(clicked) == {
        "lead_ref": str(LEAD),
        "em": sha256("ravi@example.test"),
        "li_fat_id": "li-Fictional-123",
    }
    assert microsoft_ads.identity(clicked)["msclkid"] == "msFictional1234"
    form = tiktok.identity(lead(payload={"tiktok_lead_id": "7300000000000000001"}))
    assert form == {"lead_ref": str(LEAD), "lead_id": "7300000000000000001"}


def test_what_one_event_says() -> None:
    settings = SimpleNamespace(extra={"rules": {"purchase": "9876"}})
    who = {"lead_ref": str(LEAD), "em": "e" * 64}
    li = linkedin.body(who, event_name="purchase", at=AT, settings=settings)
    assert li["conversion"] == "urn:lla:llaPartnerConversion:9876"
    assert li["conversionHappenedAt"] == int(AT.timestamp() * 1000)
    assert li["user"] == {"userIds": [{"idType": "SHA256_EMAIL", "idValue": "e" * 64}]}
    ms = microsoft_ads.body({**who, "msclkid": "msFictional1234"}, event_name="customer", at=AT)
    assert ms == {
        "ConversionName": "Sales Xray · Customer",
        "ConversionTime": "2026-10-20T09:30:00Z",
        "MicrosoftClickId": "msFictional1234",
        "HashedEmailAddress": "e" * 64,
    }
    tt = tiktok.body({**who, "lead_id": "7300000000000000001"}, event_name="Booked", at=AT)
    assert tt["event"] == "Booked" and tt["event_time"] == int(AT.timestamp())
    assert tt["lead"] == {"lead_id": "7300000000000000001", "lead_event_source": "Sales Xray"}


def test_each_platforms_answers() -> None:
    assert linkedin.read_answer(201, {}, 3).delivered
    assert linkedin.read_answer(401, {"code": "EXPIRED_ACCESS_TOKEN"}, 3).wait == "customer"
    assert linkedin.read_answer(422, {"code": "INVALID"}, 3).wait == "never"
    assert microsoft_ads.read_answer(200, {"PartialErrors": []}, 3).delivered
    bad = microsoft_ads.read_answer(
        200, {"PartialErrors": [{"ErrorCode": "OfflineConversionMicrosoftClickIdInvalid"}]}, 3
    )
    assert (bad.delivered, bad.wait) == (False, "never")
    assert tiktok.read_answer(200, {"code": 0, "request_id": "r1"}, 3).delivered
    assert tiktok.read_answer(200, {"code": 40105}, 3).wait == "customer"
    assert tiktok.read_answer(200, {"code": 50000}, 3).wait == "retry"


def test_apps_come_from_the_environment_and_connections_stay_with_their_organisation() -> None:
    assert oauth.app("linkedin", {}) is None
    cfg = oauth.app("linkedin", ENV)
    assert cfg is not None and cfg.client_id == "fictional-li-client"
    config = oauth.saved(
        {},
        cfg,
        ORG,
        tokens={"access_token": "fictional-access", "refresh_token": None},
        accounts=[{"id": "500000001", "name": "Fictional Homes ads"}],
        by=PERSON,
    )
    assert "fictional-access" not in str(config)
    assert oauth.tokens_of(config, cfg, ORG) == {
        "access_token": "fictional-access",
        "refresh_token": None,
    }
    assert oauth.tokens_of(config, cfg, OTHER) is None
    assert oauth.accounts_of(config, "linkedin") == [
        {"id": "500000001", "name": "Fictional Homes ads"}
    ]


def test_connect_goes_to_each_platforms_sign_in_with_our_state() -> None:
    for provider, adapter in (
        ("linkedin", linkedin),
        ("tiktok", tiktok),
        ("microsoft_ads", microsoft_ads),
    ):
        cfg = oauth.app(provider, ENV)
        assert cfg is not None
        url = adapter.consent_url(cfg, redirect_uri="https://example.test/cb", state="s1")
        query = parse_qs(urlparse(url).query)
        assert query["state"] == ["s1"]
        assert query["redirect_uri"] == ["https://example.test/cb"]
    ms = oauth.app("microsoft_ads", ENV)
    assert ms is not None
    assert microsoft_ads.consent_url(ms, redirect_uri="x", state="s").startswith(
        "https://login.windows-ppe.net/"
    )  # the sandbox's own sign-in
