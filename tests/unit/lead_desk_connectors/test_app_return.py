"""Connect from the Sales Xray app: the sealed hand-off back to the app and its checks."""

import base64
import html
import re
from typing import Any
from uuid import uuid4

import pytest

from ac_platform.lead_desk.connectors import app_return, meta
from ac_platform.lead_desk.connectors import google_ads_api as gads

KEY = b"k" * 32
# RFC 7636, appendix B: a verifier and the S256 challenge it answers.
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_the_challenge_is_the_s256_of_the_verifier() -> None:
    assert app_return.challenge_of(VERIFIER) == CHALLENGE
    assert app_return.answers(CHALLENGE, VERIFIER)
    assert not app_return.answers(CHALLENGE, VERIFIER[:-1] + "A")
    assert not app_return.answers(None, VERIFIER)
    assert not app_return.answers(CHALLENGE + "=", VERIFIER)
    assert not app_return.answers(CHALLENGE, "short")
    assert not app_return.answers(CHALLENGE, VERIFIER + "!")


def test_a_hand_off_opens_only_for_its_provider_with_our_key_while_fresh() -> None:
    sealed = app_return.seal(KEY, provider="meta", code="code-1", state="state-1", now=1000)
    assert "code-1" not in sealed and "state-1" not in sealed
    assert re.fullmatch(r"[A-Za-z0-9_-]+", sealed)
    assert app_return.open_(KEY, sealed, provider="meta", now=1001) == ("code-1", "state-1")
    with pytest.raises(app_return.HandoffError):
        app_return.open_(KEY, sealed, provider="google", now=1001)
    with pytest.raises(app_return.HandoffError):
        app_return.open_(b"o" * 32, sealed, provider="meta", now=1001)
    with pytest.raises(app_return.HandoffError, match="too long"):
        app_return.open_(KEY, sealed, provider="meta", now=1000 + app_return.HANDOFF_SECONDS + 1)
    flipped = sealed[:30] + ("A" if sealed[30] != "A" else "B") + sealed[31:]
    for bad in (flipped, "not a hand-off", "x" * 25, ""):
        with pytest.raises(app_return.HandoffError):
            app_return.open_(KEY, bad, provider="meta", now=1001)


def test_two_seals_of_the_same_code_differ() -> None:
    one = app_return.seal(KEY, provider="whatsapp", code="c", state="s")
    two = app_return.seal(KEY, provider="whatsapp", code="c", state="s")
    assert one != two


def _target(page: Any) -> str:
    """Where the page sends the browser: its meta refresh, the same as its link."""
    assert page.status_code == 200
    assert "location" not in page.headers
    body = bytes(page.body).decode()
    refresh = re.search(r'http-equiv="refresh" content="0;url=([^"]+)"', body)
    link = re.search(r'<a href="([^"]+)"', body)
    assert refresh is not None and link is not None
    assert refresh.group(1) == link.group(1)
    return html.unescape(refresh.group(1))


def test_the_return_page_sends_the_browser_back_to_the_app() -> None:
    sealed = app_return.seal(KEY, provider="meta", code="code-1", state="s")
    page = app_return.return_page("meta", handoff=sealed)
    assert page.headers["cache-control"] == "no-store"
    assert page.headers["referrer-policy"] == "no-referrer"
    target = _target(page)
    assert target == (
        f"{app_return.APP_RETURN}#provider=meta&path=/leads%3Ftab%3Dsources&handoff={sealed}"
    )
    assert "code-1" not in bytes(page.body).decode()
    # No script: the /v1 policy allows none, and a meta refresh needs none.
    assert "<script" not in bytes(page.body).decode()


def test_the_return_page_carries_only_a_known_word_without_a_hand_off() -> None:
    cancelled = _target(app_return.return_page("google", result="cancelled"))
    assert cancelled.endswith("#provider=google&path=/leads%3Ftab%3Dsources&result=cancelled")
    odd = _target(app_return.return_page("whatsapp", result="<b>"))
    assert odd.endswith("path=/organisation%3Ftab%3Dintegrations&result=failed")


def test_an_app_state_carries_its_challenge_and_peeks_for_anyone() -> None:
    tenant, person = uuid4(), uuid4()
    state = meta.make_state(
        "s", tenant_id=tenant, person_id=person, now=1000, app_challenge=CHALLENGE
    )
    assert meta.peek_state("s", state, now=1001)["a"] == CHALLENGE
    assert meta.read_state("s", state, tenant_id=tenant, person_id=person, now=1001)["a"] == (
        CHALLENGE
    )
    with pytest.raises(meta.MetaError):
        meta.read_state("s", state, tenant_id=tenant, person_id=uuid4(), now=1001)
    with pytest.raises(meta.MetaError):
        meta.peek_state("other", state, now=1001)
    with pytest.raises(meta.MetaError, match="too long"):
        meta.peek_state("s", state, now=1000 + meta.STATE_SECONDS + 1)
    web = meta.make_state("s", tenant_id=tenant, person_id=person, now=1000)
    assert "a" not in meta.peek_state("s", web, now=1001)


def test_a_google_app_state_reads_back_with_google_words() -> None:
    cfg = gads.config(
        {
            "AC_GOOGLE_ADS_CLIENT_ID": "client-1.apps.googleusercontent.com",
            "AC_GOOGLE_ADS_CLIENT_SECRET": "client-secret",
            "AC_GOOGLE_ADS_DEVELOPER_TOKEN": "dev-token",
            "AC_LEAD_DESK_TOKEN_KEY": base64.urlsafe_b64encode(KEY).decode(),
        }
    )
    assert cfg is not None
    tenant, person = uuid4(), uuid4()
    state = gads.make_state(cfg, tenant_id=tenant, person_id=person, app_challenge=CHALLENGE)
    assert gads.peek_state(cfg, state)["a"] == CHALLENGE
    with pytest.raises(gads.GoogleAdsApiError, match="Google"):
        gads.peek_state(cfg, state + "x")


def test_a_settings_connect_comes_back_to_its_card_only() -> None:
    from ac_platform.lead_desk.connectors.app_return import card_of, settings_card, settings_url

    cards = ("messenger", "instagram")
    assert settings_card(None, None, allowed=cards) is None  # the old destination
    assert settings_card("/settings/apps", None, allowed=cards) == "messenger"
    assert settings_card("/settings/apps", "instagram", allowed=cards) == "instagram"
    for bad in (("https://elsewhere.example", None), ("/settings/apps", "whatsapp")):
        with pytest.raises(ValueError):
            settings_card(*bad, allowed=cards)
    app = "https://salesxray.example"
    assert settings_url(app, "whatsapp", "connected") == f"{app}/settings/apps?connected=whatsapp"
    assert [
        settings_url(app, "messenger", outcome).split("=")[-1]
        for outcome in ("cancelled", "failed", "taken", "nopages", "noaccounts", "nonumbers", "odd")
    ] == ["cancelled", "failed", "in_use", "no_pages", "no_accounts", "no_numbers", "failed"]
    assert card_of({"r": "instagram"}, cards) == "instagram"
    assert card_of({"r": "elsewhere"}, cards) is None and card_of(None, cards) is None
