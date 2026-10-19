"""Ad spend per Meta campaign on PostgreSQL, with Meta's Marketing API faked.

An organisation that connected Meta gets each campaign's daily spend read; the same
day read again replaces itself; cost per lead counts the Meta leads that arrived here
from the campaign, cost per customer the ones now won; a lost connection is shown
plainly; a manager can read it now; a seller can't see it.
"""

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select, update

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.connectors import meta, meta_capi, meta_spend
from ac_platform.lead_desk.connectors.http import install_connectors_http
from ac_platform.lead_desk.models import Lead, LeadAdSpendDay, LeadDeskSettings
from ac_platform.lead_desk.store import LeadDesk, Viewer
from ac_platform.tenancy.models import Membership
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_meta_postgresql import ENV, META
from tests.database.test_lead_desk_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
CAMPAIGN = "120000000000001"
OTHER = "120000000000002"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def handler_for(spend: dict[str, str], *, refused: list[bool]) -> Any:
    """Meta: one ad account, two campaigns, each with yesterday's and today's spend."""

    def handler(request: httpx.Request) -> httpx.Response:
        if refused[0]:
            return httpx.Response(400, json={"error": {"code": 190, "message": "expired"}})
        query = {key: values[0] for key, values in parse_qs(request.url.query.decode()).items()}
        assert query["access_token"] == "org-user-token"  # noqa: S105 - the fake's own token
        if request.url.path.endswith("/me/adaccounts"):
            return httpx.Response(200, json={"data": [{"id": "act_101", "name": "Fictional ads"}]})
        assert request.url.path.endswith("/act_101/insights")
        today = datetime.now(UTC).date()
        rows = [
            {
                "campaign_id": campaign,
                "campaign_name": name,
                "spend": spend[f"{campaign}:{day}"],
                "impressions": "1000",
                "clicks": "40",
                "actions": [{"action_type": "lead", "value": "3"}],
                "account_currency": "INR",
                "date_start": day.isoformat(),
            }
            for campaign, name in ((CAMPAIGN, "3 BHK enquiries"), (OTHER, "Site visits"))
            for day in (today - timedelta(days=1), today)
        ]
        return httpx.Response(200, json={"data": rows})

    return handler


def test_spend_per_campaign_and_cost_per_lead(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    cfg = meta.config()
    assert cfg is not None
    today = datetime.now(UTC).date()
    spend = {
        f"{CAMPAIGN}:{today - timedelta(days=1)}": "600.00",
        f"{CAMPAIGN}:{today}": "400.00",
        f"{OTHER}:{today - timedelta(days=1)}": "90.00",
        f"{OTHER}:{today}": "10.00",
    }
    refused = [False]
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler_for(spend, refused=refused)))
    real = meta.Graph
    monkeypatch.setattr(meta, "Graph", lambda cfg, *args, **kwargs: real(cfg, client))

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            install_connectors_http(
                setup.app, RouteContext(settings, setup.require_actor, setup.sessions)
            )
            tenant = setup.state.tenant_id
            # What Continue with Meta left: the organisation's own sealed connection.
            async with setup.sessions() as db, db.begin():
                db.add(
                    LeadDeskSettings(
                        tenant_id=tenant,
                        revision=1,
                        config={
                            meta_capi.CONNECTION: {
                                "token": meta.seal(
                                    cfg.token_key,
                                    "org-user-token",
                                    page_id=meta_capi.connection_bound(tenant),
                                ),
                                "at": int(time.time()),
                            }
                        },
                        updated_by_person_id=None,
                        updated_at=datetime.now(UTC),
                    )
                )
                desk = LeadDesk(
                    db,
                    Viewer(
                        person_id=setup.state.person_id,
                        tenant_id=tenant,
                        role="admin",
                        name="Admin",
                    ),
                )
                for n, campaign in enumerate((CAMPAIGN, CAMPAIGN, CAMPAIGN, CAMPAIGN, OTHER)):
                    await desk.ingest(
                        {
                            "name": f"Fictional Lead {n}",
                            "phone": f"+9199990000{n:02d}",
                            "meta": {"campaign_id": campaign},
                        },
                        source="meta",
                        source_ref=f"lead-{n}",
                        actor=None,
                    )
            async with setup.sessions() as db, db.begin():
                first = await db.scalar(select(Lead).where(Lead.source_ref == "lead-0"))
                assert first is not None
                await db.execute(update(Lead).where(Lead.id == first.id).values(stage="won"))

            graph = real(cfg, client)
            done = await meta_spend.tick(setup.sessions, cfg, graph, now=datetime.now(UTC))
            assert (done.tenants, done.rows, done.failed) == (1, 4, [])
            # Within the hour nothing is read again; the same day read again replaces itself.
            assert (
                await meta_spend.tick(setup.sessions, cfg, graph, now=datetime.now(UTC))
            ).tenants == 0
            spend[f"{CAMPAIGN}:{today}"] = "500.00"
            later = datetime.now(UTC) + timedelta(hours=2)
            assert (await meta_spend.tick(setup.sessions, cfg, graph, now=later)).rows == 4
            async with setup.sessions() as db:
                assert await db.scalar(select(func.count()).select_from(LeadAdSpendDay)) == 4

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as http:
                http.cookies.set(setup.settings.session_cookie_name, setup.token)
                view = (await http.get(f"{META}/spend", params={"days": 7})).json()
                assert view["connected"] is True and view["error"] is None
                assert view["accounts"] == 1 and view["syncedAt"]
                [big, small] = view["campaigns"]
                assert (big["campaignName"], big["spend"], big["metaLeads"]) == (
                    "3 BHK enquiries",
                    "1100.00",
                    6,
                )
                assert (big["leads"], big["won"], big["perLead"], big["perCustomer"]) == (
                    4,
                    1,
                    "275.00",
                    "1100.00",
                )
                assert (small["leads"], small["perLead"], small["perCustomer"]) == (
                    1,
                    "100.00",
                    None,
                )
                assert view["totals"] == [
                    {
                        "currency": "INR",
                        "spend": "1200.00",
                        "leads": 5,
                        "won": 1,
                        "perLead": "240.00",
                    }
                ]
                # Meta ended the connection: the page says so, the numbers stay.
                refused[0] = True
                now = await http.post(f"{META}/spend/refresh", headers=WRITE)
                assert now.status_code == 200, now.text
                assert now.json()["error"] and now.json()["syncedAt"] == view["syncedAt"]
                assert len(now.json()["campaigns"]) == 2

                # A seller doesn't see the organisation's ad spend.
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(Membership)
                        .where(Membership.person_id == setup.state.person_id)
                        .values(role="member")
                    )
                assert (await http.get(f"{META}/spend")).status_code == 403
        finally:
            await client.aclose()
            await setup.engine.dispose()

    run(exercise())
