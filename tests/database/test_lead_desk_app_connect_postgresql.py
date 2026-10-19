"""Connect from the Sales Xray app on PostgreSQL, with Meta and Google faked.

Facebook and Google refuse sign-in inside the app's web view, so in the app a Connect
opens in the phone's browser, which has no Sales Xray session. The page asks for the
sign-in address with a challenge; the provider comes back to the callback in that
browser, which connects nothing and hands a sealed result to the app; the app's page
finishes the Connect on its own session with the verifier. A wrong verifier, another
person's state, another provider's hand-off or no session connects nothing. The web
flow (a browser with a session) is unchanged.
"""

import html
import json
import re
import secrets
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, parse_qsl, urlparse
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.connectors import app_return, meta
from ac_platform.lead_desk.connectors import google_ads_api as gads
from ac_platform.lead_desk.connectors.http import install_connectors_http
from ac_platform.lead_desk.models import LeadSource, LeadWhatsAppNumber
from ac_platform.lead_desk.whatsapp import cloud
from ac_platform.lead_desk.whatsapp.http import install_whatsapp_http
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_meta_postgresql import ENV as META_ENV
from tests.database.test_lead_desk_meta_postgresql import META, FakeGraph
from tests.database.test_lead_desk_postgresql import _organisation
from tests.database.test_lead_desk_whatsapp_postgresql import FakeCloud
from tests.unit.lead_desk_connectors.test_google_ads_api import ENV as GOOGLE_ENV
from tests.unit.lead_desk_whatsapp.test_whatsapp_cloud import ENV as WHATSAPP_ENV

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
BASE = "/v1/lead-desk"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


class FakeAds:
    """Google's OAuth and Google Ads API for one fictional advertiser."""

    def __init__(self, cfg: gads.GoogleAdsConfig, client: Any = None) -> None:
        self.cfg = cfg

    async def refresh_token(self, *, code: str, redirect_uri: str) -> str:
        assert code == "google-code"
        assert redirect_uri.endswith("/v1/lead-desk/google/callback")
        return "fake-refresh-token"

    async def access_token(self, refresh_token: str) -> str:
        assert refresh_token == "fake-refresh-token"  # noqa: S105 - the fake's own token
        return "fake-access-token"

    async def accounts(self, access: str) -> list[gads.Account]:
        return [
            gads.Account(
                customer_id="1234567890",
                name="Fictional Homes ads",
                login_customer_id=None,
                test=True,
            )
        ]


def _verifier() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    return verifier, app_return.challenge_of(verifier)


def _back_to_app(page: httpx.Response) -> dict[str, str]:
    """What the callback hands the app: the fragment of the app address it opens."""
    assert page.status_code == 200, page.text
    assert page.headers["content-type"].startswith("text/html")
    assert "location" not in page.headers  # the hand-off stays out of edge logs
    assert page.headers["cache-control"] == "no-store"
    assert page.headers["referrer-policy"] == "no-referrer"
    refresh = re.search(r'http-equiv="refresh" content="0;url=([^"]+)"', page.text)
    assert refresh is not None
    target = html.unescape(refresh.group(1))
    assert target.startswith(app_return.APP_RETURN + "#")
    return dict(parse_qsl(target.split("#", 1)[1]))


async def _sources(setup: Any, kind: str) -> list[LeadSource]:
    async with setup.sessions() as db:
        rows = await db.scalars(
            select(LeadSource).where(
                LeadSource.tenant_id == setup.state.tenant_id, LeadSource.kind == kind
            )
        )
        return list(rows.all())


def test_meta_connect_in_the_app_finishes_through_the_phones_browser(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in META_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(meta, "Graph", FakeGraph)
    cfg = meta.config()
    assert cfg is not None

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            install_connectors_http(
                setup.app, RouteContext(settings, setup.require_actor, setup.sessions)
            )
            transport = httpx.ASGITransport(app=setup.app)
            async with (
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as app,
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as browser,
            ):
                app.cookies.set(setup.settings.session_cookie_name, setup.token)
                verifier, challenge = _verifier()

                odd = await app.get(f"{META}/connect", params={"app_challenge": "short"})
                assert odd.status_code == 422
                started = await app.get(
                    f"{META}/connect", params={"app_challenge": challenge, "format": "json"}
                )
                assert started.status_code == 200, started.text
                dialog = started.json()["url"]
                assert dialog.startswith("https://www.facebook.com/")
                state = parse_qs(urlparse(dialog).query)["state"][0]
                assert meta.peek_state(cfg.app_secret, state)["a"] == challenge

                # Meta returns to the callback in the phone's browser, which has no
                # Sales Xray session: it hands the result to the app and connects nothing.
                cancelled = await browser.get(
                    f"{META}/callback", params={"error": "access_denied", "state": state}
                )
                assert _back_to_app(cancelled) == {
                    "provider": "meta",
                    "path": "/leads?tab=sources",
                    "result": "cancelled",
                }
                back = _back_to_app(
                    await browser.get(
                        f"{META}/callback", params={"code": "meta-code", "state": state}
                    )
                )
                assert (back["provider"], back["path"]) == ("meta", "/leads?tab=sources")
                handoff = back["handoff"]
                assert "meta-code" not in handoff
                assert await _sources(setup, "meta") == []

                finish = f"{META}/app-complete"
                mine = {"handoff": handoff, "verifier": verifier}
                # Without the person's own session the hand-off does nothing.
                assert (await browser.post(finish, json=mine, headers=WRITE)).status_code == 401
                # Not the verifier the page kept.
                wrong = await app.post(
                    finish, json={"handoff": handoff, "verifier": _verifier()[0]}, headers=WRITE
                )
                assert wrong.status_code == 403, wrong.text
                # A Google hand-off can't finish Meta; a broken one says start again.
                google = app_return.seal(
                    cfg.token_key, provider="google", code="meta-code", state=state
                )
                for bad in (google, "x" * 40):
                    refused = await app.post(
                        finish, json={"handoff": bad, "verifier": verifier}, headers=WRITE
                    )
                    assert refused.status_code == 422, refused.text
                # Someone else's sign-in in this workspace.
                theirs = meta.make_state(
                    cfg.app_secret,
                    tenant_id=setup.state.tenant_id,
                    person_id=uuid4(),
                    app_challenge=challenge,
                )
                sealed = app_return.seal(
                    cfg.token_key, provider="meta", code="meta-code", state=theirs
                )
                other = await app.post(
                    finish, json={"handoff": sealed, "verifier": verifier}, headers=WRITE
                )
                assert other.status_code == 403, other.text
                assert await _sources(setup, "meta") == []

                done = await app.post(finish, json=mine, headers=WRITE)
                assert done.status_code == 200, done.text
                assert done.json() == {"result": "connected"}
                pages = await _sources(setup, "meta")
                assert [(p.config["page_id"], p.active) for p in pages] == [("p1", False)]
                view = (await app.get(f"{META}/conversions")).json()
                assert view["connected"] is True

                # In a browser with a session, Continue with Meta is as before.
                web = await app.get(f"{META}/connect")
                assert web.status_code == 303
                web_state = parse_qs(urlparse(web.headers["location"]).query)["state"][0]
                assert "a" not in meta.peek_state(cfg.app_secret, web_state)
                plain = await app.get(
                    f"{META}/callback", params={"code": "meta-code", "state": web_state}
                )
                assert plain.status_code == 303, plain.text
                assert plain.headers["location"].endswith("/leads?tab=sources&meta=connected")
                assert len(await _sources(setup, "meta")) == 1
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_google_connect_in_the_app_finishes_through_the_phones_browser(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in GOOGLE_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(gads, "Ads", FakeAds)
    cfg = gads.config()
    assert cfg is not None

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            install_connectors_http(
                setup.app, RouteContext(settings, setup.require_actor, setup.sessions)
            )
            transport = httpx.ASGITransport(app=setup.app)
            async with (
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as app,
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as browser,
            ):
                app.cookies.set(setup.settings.session_cookie_name, setup.token)
                verifier, challenge = _verifier()
                started = await app.get(
                    f"{BASE}/google/connect",
                    params={"app_challenge": challenge, "format": "json"},
                )
                assert started.status_code == 200, started.text
                consent = started.json()["url"]
                assert consent.startswith(gads.AUTH)
                state = parse_qs(urlparse(consent).query)["state"][0]

                back = _back_to_app(
                    await browser.get(
                        f"{BASE}/google/callback", params={"code": "google-code", "state": state}
                    )
                )
                assert (back["provider"], back["path"]) == ("google", "/leads?tab=sources")
                assert (
                    _back_to_app(
                        await browser.get(f"{BASE}/google/callback", params={"state": state})
                    )["result"]
                    == "failed"
                )
                assert await _sources(setup, "webhook") == []

                finish = f"{BASE}/google/app-complete"
                wrong = await app.post(
                    finish,
                    json={"handoff": back["handoff"], "verifier": _verifier()[0]},
                    headers=WRITE,
                )
                assert wrong.status_code == 403, wrong.text
                meta_handoff = app_return.seal(
                    cfg.token_key, provider="meta", code="google-code", state=state
                )
                refused = await app.post(
                    finish, json={"handoff": meta_handoff, "verifier": verifier}, headers=WRITE
                )
                assert refused.status_code == 422, refused.text
                assert await _sources(setup, "webhook") == []

                done = await app.post(
                    finish, json={"handoff": back["handoff"], "verifier": verifier}, headers=WRITE
                )
                assert done.status_code == 200, done.text
                assert done.json() == {"result": "connected"}
                accounts = await _sources(setup, "webhook")
                assert [(a.config["customer_id"], a.active) for a in accounts] == [
                    ("1234567890", False)
                ]
                assert "fake-refresh-token" not in json.dumps(accounts[0].config)

                web = await app.get(f"{BASE}/google/connect")
                assert web.status_code == 303
                assert web.headers["location"].startswith(gads.AUTH)
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_whatsapp_connect_in_the_app_finishes_through_the_phones_browser(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in WHATSAPP_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(cloud, "Cloud", FakeCloud)
    FakeCloud.templates_at_meta = []
    cfg = cloud.config()
    assert cfg is not None

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            install_whatsapp_http(
                setup.app, RouteContext(settings, setup.require_actor, setup.sessions)
            )
            transport = httpx.ASGITransport(app=setup.app)
            async with (
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as app,
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as browser,
            ):
                app.cookies.set(setup.settings.session_cookie_name, setup.token)
                verifier, challenge = _verifier()
                odd = await app.get(f"{BASE}/whatsapp/start", params={"app_challenge": "x"})
                assert odd.status_code == 422
                started = await app.get(
                    f"{BASE}/whatsapp/start",
                    params={"app_challenge": challenge, "format": "json"},
                )
                assert started.status_code == 200, started.text
                dialog = started.json()["url"]
                state = parse_qs(urlparse(dialog).query)["state"][0]

                back = _back_to_app(
                    await browser.get(
                        f"{BASE}/whatsapp/callback",
                        params={"code": "signup-code", "state": state},
                    )
                )
                assert (back["provider"], back["path"]) == (
                    "whatsapp",
                    "/organisation?tab=integrations",
                )
                async with setup.sessions() as db:
                    assert await db.scalar(select(LeadWhatsAppNumber)) is None

                finish = f"{BASE}/whatsapp/app-complete"
                wrong = await app.post(
                    finish,
                    json={"handoff": back["handoff"], "verifier": _verifier()[0]},
                    headers=WRITE,
                )
                assert wrong.status_code == 403, wrong.text
                done = await app.post(
                    finish, json={"handoff": back["handoff"], "verifier": verifier}, headers=WRITE
                )
                assert done.status_code == 200, done.text
                assert done.json() == {"result": "connected"}
                status = (await app.get(f"{BASE}/whatsapp/status")).json()
                assert [n["displayNumber"] for n in status["numbers"]] == ["+91 80000 00000"]
        finally:
            await setup.engine.dispose()

    run(exercise())
