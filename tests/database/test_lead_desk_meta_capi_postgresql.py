"""Lead stages back to the organisation's Meta dataset (Conversions API for CRM), on
PostgreSQL with Meta faked.

Continue with Meta, create a dataset, win one lead and lose another: every stage
reaches Meta once, with Meta's lead id and hashes only; a lost connection waits for
the customer and then goes out; the page shows the delivery log.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.connectors import meta, meta_capi
from ac_platform.lead_desk.connectors.http import install_connectors_http
from ac_platform.lead_desk.models import Lead, LeadMetaConversion, LeadMetaConversionAttempt
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_meta_postgresql import ENV, META, USER_TOKEN, FakeGraph
from tests.database.test_lead_desk_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_lead_stages_go_back_to_the_organisations_meta_dataset(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(meta, "Graph", FakeGraph)
    FakeGraph.forms_listed = ["fa"]
    cfg = meta.config()
    assert cfg is not None
    posts: list[dict[str, str]] = []
    refuse_first = [True]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v23.0/777000222/events"
        form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
        if refuse_first[0]:
            refuse_first[0] = False
            return httpx.Response(400, json={"error": {"code": 190, "fbtrace_id": "T0"}})
        posts.append(form)
        return httpx.Response(200, json={"events_received": 1, "fbtrace_id": f"T{len(posts)}"})

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            install_connectors_http(
                setup.app, RouteContext(settings, setup.require_actor, setup.sessions)
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                state = meta.make_state(
                    cfg.app_secret,
                    tenant_id=setup.state.tenant_id,
                    person_id=setup.state.person_id,
                )
                back = await client.get(
                    f"{META}/callback", params={"code": "meta-code", "state": state}
                )
                assert back.status_code == 303, back.text
                assert back.headers["location"].endswith("meta=connected")
                view = (await client.get(f"{META}/conversions")).json()
                assert (view["connected"], view["dataset"], view["on"]) == (True, None, False)
                assert view["events"]["new"] == "Lead" and view["connectionExpiresAt"]

                found = (await client.get(f"{META}/datasets")).json()
                assert found["datasets"] == [{"id": "777000111", "name": "Fictional Homes website"}]
                assert found["adAccounts"][0]["id"] == "act_10000001"
                made = await client.post(
                    f"{META}/datasets",
                    json={"adAccountId": "act_10000001", "name": "Sales Xray CRM"},
                    headers=WRITE,
                )
                assert made.status_code == 201, made.text
                saved = await client.put(
                    f"{META}/conversions",
                    json={
                        "datasetId": made.json()["id"],
                        "datasetName": "Sales Xray CRM",
                        "on": True,
                        "events": {"lost": "Not a fit"},
                        "testCode": "TEST4321",
                    },
                    headers=WRITE,
                )
                assert saved.status_code == 200, saved.text
                assert saved.json()["dataset"] == {"id": "777000222", "name": "Sales Xray CRM"}
                assert saved.json()["on"] is True
                refused = await client.put(
                    f"{META}/conversions",
                    json={
                        "datasetId": "777000222",
                        "datasetName": "Sales Xray CRM",
                        "on": True,
                        "events": {"won": "Lead"},
                    },
                    headers=WRITE,
                )
                assert refused.status_code == 422

                on = await client.post(f"{META}/pages/p1", json={}, headers=WRITE)
                assert on.status_code == 200, on.text
                assert on.json()["imported"] == 2
                async with setup.sessions() as db:
                    leads = {lead.source_ref: lead for lead in (await db.scalars(select(Lead)))}
                for ref, stage in (("100000000000001", "won"), ("100000000000002", "lost")):
                    lead = leads[ref]
                    done = await client.post(
                        f"/v1/lead-desk/leads/{lead.id}/dispose",
                        json={
                            "command_id": str(uuid4()),
                            "expected_revision": lead.revision,
                            "connected": True,
                            "stage": stage,
                        },
                        headers=WRITE,
                    )
                    assert done.status_code == 200, done.text

                # Lead Desk events are read once they have settled (5 minutes).
                now = datetime.now(UTC)
                assert await meta_capi.collect(setup.sessions, environment="dev", now=now) == 0
                later = now + timedelta(minutes=10)
                assert await meta_capi.collect(setup.sessions, environment="dev", now=later) == 6
                assert await meta_capi.collect(setup.sessions, environment="dev", now=later) == 0
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                    async with setup.sessions() as db, db.begin():
                        lines = await meta_capi.deliver(db, http, cfg, now=later)
                    assert len(lines) == 6 and len(posts) == 5
                    view = (await client.get(f"{META}/conversions")).json()
                    assert view["counts"] == {"delivered": 5, "pending": 1}
                    assert view["waitingOn"].startswith("Meta ended the connection")
                    async with setup.sessions() as db, db.begin():
                        await meta_capi.deliver(db, http, cfg, now=later + timedelta(minutes=30))
                    assert len(posts) == 5  # it waits an hour for the customer
                    async with setup.sessions() as db, db.begin():
                        await meta_capi.deliver(db, http, cfg, now=later + timedelta(hours=2))
                    assert len(posts) == 6

                view = (await client.get(f"{META}/conversions")).json()
                assert view["counts"] == {"delivered": 6} and view["waitingOn"] is None
                assert view["lastDeliveredAt"]
                assert sorted(item["eventName"] for item in view["recent"]) == sorted(
                    ["Lead", "Lead", "Follow-up", "Interested", "Won", "Not a fit"]
                )
                assert {item["leadName"] for item in view["recent"]} == {
                    "Test Lead 1",
                    "Test Lead 2",
                }

            sent = [json.loads(post["data"])[0] for post in posts]
            assert all(post["access_token"] == USER_TOKEN for post in posts)
            assert all(post["test_event_code"] == "TEST4321" for post in posts)
            assert {(event["user_data"]["lead_id"], event["event_name"]) for event in sent} == {
                (100000000000001, "Lead"),
                (100000000000001, "Follow-up"),
                (100000000000001, "Interested"),
                (100000000000001, "Won"),
                (100000000000002, "Lead"),
                (100000000000002, "Not a fit"),
            }
            for event in sent:
                assert event["action_source"] == "system_generated"
                assert event["custom_data"] == {
                    "event_source": "crm",
                    "lead_event_source": "Sales Xray",
                }
                assert set(event["user_data"]) == {"lead_id", "ph"}
                assert "99990" not in json.dumps(event)  # the phone goes hashed only
            async with setup.sessions() as db:
                attempts = await db.scalar(
                    select(func.count()).select_from(LeadMetaConversionAttempt)
                )
                assert attempts == 7
                rows = (await db.scalars(select(LeadMetaConversion))).all()
                assert {row.status for row in rows} == {"delivered"}
                assert all(row.fbtrace_id for row in rows)
        finally:
            await setup.engine.dispose()

    run(exercise())
