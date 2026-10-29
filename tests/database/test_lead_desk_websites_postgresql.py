"""The website line end to end on PostgreSQL (owner, 30 Oct 2026: connecting websites and
landing pages in one step; lead_desk/websites.py).

A manager starts the Websites card and gets one line with the organisation's key. A page
with the line says hello and the site appears by itself; a lead form sent on it becomes a
lead with its answers, its page and where the visit came from; the same person sending
again soon is one lead; bots, other people's pages, paused and removed sites add nothing;
and the public key can't be used on the generic capture route.
"""

from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk import websites
from ac_platform.lead_desk.journey.providers import click_ids
from ac_platform.lead_desk.models import Lead, LeadSite, LeadSitePage, LeadSource
from ac_platform.lead_desk.websites_http import install_websites_http
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation

BASE = "/v1/lead-desk"
WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
SITE = "https://www.fictionalclinic.example.com"
PAGE = f"{SITE}/book?utm_source=google&utm_medium=cpc&utm_campaign=Diwali&gclid=Cj0KCQ-fict"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def _from(site: str) -> dict[str, str]:
    """What a browser sends from a page on ``site``: its Origin, the script's text body."""
    return {"Origin": site, "Content-Type": "text/plain"}


def _lead(key: str, **changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "k": key,
        "u": PAGE,
        "t": "Book a consultation",
        "form": "Book",
        "fields": [
            {"k": "Full name", "v": "Asha Fictional", "r": "name"},
            {"k": "Mobile number", "v": "98765 00041", "r": "phone"},
            {"k": "Email", "v": "asha@fictional.example.com", "r": "email"},
            {"k": "Which treatment?", "v": "Physiotherapy"},
            {"k": "Password", "v": "never-kept"},
        ],
        "a": {
            "last": {
                "utm_source": "google",
                "utm_medium": "cpc",
                "utm_campaign": "Diwali",
                "gclid": "Cj0KCQ-fict",
                "fbp": "fb.1.1730280000000.1234567890",
            },
            "first": {"utm_source": "newsletter", "at": 1729000000000},
        },
        "it": 14,
        "ms": 21000,
        "wd": False,
        "p": "wordpress",
    }
    body.update(changes)
    return body


def test_one_line_turns_a_websites_form_into_a_lead_with_its_source(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            install_websites_http(
                setup.app, RouteContext(settings, setup.require_actor, setup.sessions)
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                # Before anyone starts, a read makes nothing.
                empty = await client.get(f"{BASE}/websites")
                assert empty.status_code == 200, empty.text
                assert (empty.json()["key"], empty.json()["sites"]) == (None, [])
                started = await client.post(f"{BASE}/websites/start", headers=WRITE)
                assert started.status_code == 200, started.text
                card = started.json()
                key = card["key"]
                assert websites.KEY_PATTERN.fullmatch(key)
                assert card["snippet"] == (
                    f'<script src="{ORIGIN}/sx.js" data-key="{key}" async></script>'
                )
                client.cookies.clear()

                # The page says hello: the site appears by itself, waiting no more.
                hello = await client.post(
                    f"{BASE}/site/hello",
                    json={"k": key, "u": PAGE, "t": "Book", "f": 2, "p": "wordpress"},
                    headers=_from(SITE),
                )
                assert hello.status_code == 200, hello.text
                assert hello.json() == {"ok": True, "site": "active"}
                assert hello.headers["access-control-allow-origin"] == SITE
                assert "set-cookie" not in hello.headers

                # Someone else's page with the same key: nothing.
                stranger = await client.post(
                    f"{BASE}/site/hello",
                    json={"k": key, "u": PAGE},
                    headers=_from("https://someone-else.example.com"),
                )
                assert stranger.status_code == 403

                sent = await client.post(f"{BASE}/site/lead", json=_lead(key), headers=_from(SITE))
                assert sent.status_code == 202, sent.text
                assert sent.json() == {"received": True, "outcome": "received"}
                again = await client.post(f"{BASE}/site/lead", json=_lead(key), headers=_from(SITE))
                assert again.json()["received"] is True

                # A headless browser, and a form sent in a blink with no key pressed.
                for bot in (_lead(key, wd=True), _lead(key, it=0, ms=300)):
                    turned = await client.post(f"{BASE}/site/lead", json=bot, headers=_from(SITE))
                    assert turned.json() == {"received": True, "outcome": "received"}
                # No phone or email: nothing to call.
                nothing = await client.post(
                    f"{BASE}/site/lead",
                    json=_lead(key, fields=[{"k": "Name", "v": "Only A Name", "r": "name"}]),
                    headers=_from(SITE),
                )
                assert nothing.json() == {"received": False, "outcome": "no_contact"}

                # The public key is not a generic source key.
                async with setup.sessions() as db:
                    source = await db.scalar(
                        select(LeadSource).where(LeadSource.tenant_id == setup.state.tenant_id)
                    )
                assert source is not None and source.config["website"]["key"] == key
                generic = await client.post(
                    f"{BASE}/capture/{source.id}",
                    json={"name": "Generic", "phone": "+919876500042"},
                    headers={"X-Lead-Desk-Key": key},
                )
                assert generic.status_code in (401, 404)

            async with setup.sessions() as db:
                leads = (await db.scalars(select(Lead))).all()
                site = await db.scalar(select(LeadSite))
                pages = (await db.scalars(select(LeadSitePage))).all()
            assert len(leads) == 1
            lead = leads[0]
            assert (lead.name, lead.phone, lead.email) == (
                "Asha Fictional",
                "+919876500041",
                "asha@fictional.example.com",
            )
            assert lead.source == "webhook" and not lead.test_data
            assert lead.source_label == "Website · fictionalclinic.example.com"
            assert "Password" not in lead.payload
            assert lead.payload["Which treatment?"] == "Physiotherapy"
            assert lead.payload["Page"] == f"{SITE}/book"
            assert lead.payload["Came from"] == "Google Ads · Diwali"
            assert lead.payload["attribution"]["utm_campaign"] == "Diwali"
            assert lead.payload["attribution"]["first_touch"]["utm_source"] == "newsletter"
            assert lead.payload["website"]["host"] == "fictionalclinic.example.com"
            # Google Ads (and the other platforms) read the click id from the record.
            assert click_ids(lead.payload) == {"gclid": "Cj0KCQ-fict"}
            assert site is not None
            assert (site.host, site.added, site.status, site.platform, site.leads) == (
                "fictionalclinic.example.com",
                "seen",
                "active",
                "wordpress",
                1,
            )
            assert site.first_seen_at is not None and site.last_lead_at is not None
            (page,) = pages
            assert (page.path, page.views, page.forms, page.fills, page.leads, page.blocked) == (
                "/book",
                1,
                2,
                1,  # the same person sending again at once is the same fill ("known")
                1,
                2,
            )

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                card = (await client.get(f"{BASE}/websites")).json()
                (shown,) = card["sites"]
                assert (shown["views"], shown["leads"], shown["forms"], shown["blocked"]) == (
                    1,
                    1,
                    2,
                    2,
                )
                assert shown["rate"] == 1.0
                assert shown["pages"][0]["path"] == "/book"
                site_id = shown["site_id"]

                # A test lead lands under Test leads.
                test = await client.post(f"{BASE}/websites/{site_id}/test", headers=WRITE)
                assert test.status_code == 201, test.text

                # Paused: the form adds nothing.
                paused = await client.post(
                    f"{BASE}/websites/{site_id}/status", json={"status": "paused"}, headers=WRITE
                )
                assert paused.json()["sites"][0]["status"] == "paused"
                client.cookies.clear()
                held = await client.post(
                    f"{BASE}/site/lead",
                    json=_lead(key, fields=[{"k": "Phone", "v": "98765 00043", "r": "phone"}]),
                    headers=_from(SITE),
                )
                assert held.json() == {"received": False, "outcome": "paused"}

                # Removed: it can't add itself back by saying hello.
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                removed = await client.delete(f"{BASE}/websites/{site_id}", headers=WRITE)
                assert removed.json()["sites"] == []
                client.cookies.clear()
                back = await client.post(
                    f"{BASE}/site/hello", json={"k": key, "u": PAGE}, headers=_from(SITE)
                )
                assert back.json() == {"ok": True, "site": "removed"}

                # A person adds it back; a new key stops the old line.
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                added = await client.post(
                    f"{BASE}/websites",
                    json={"address": "fictionalclinic.example.com"},
                    headers=WRITE,
                )
                assert added.json()["sites"][0]["status"] == "active"
                rotated = (await client.post(f"{BASE}/websites/key", headers=WRITE)).json()
                assert rotated["key"] != key
                client.cookies.clear()
                old = await client.post(
                    f"{BASE}/site/hello", json={"k": key, "u": PAGE}, headers=_from(SITE)
                )
                assert old.status_code == 401

            async with setup.sessions() as db:
                tests = (await db.scalars(select(Lead).where(Lead.test_data.is_(True)))).all()
            assert len(tests) == 1 and tests[0].payload["Came from"] == "Sales-xray · website-test"
        finally:
            await setup.engine.dispose()

    run(exercise())
