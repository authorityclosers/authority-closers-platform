"""When each lead came in (owner, 16 Nov 2026: "when did this lead actually generate?").

The list filters by when the person sent the lead (Yesterday, and a range of days), sorts
newest first by that time, and each row carries when it was added, last changed and given
to its owner. Leads per day counts the same leads for owners and managers only; a seller
is refused. Disposable loopback PostgreSQL, fictional rows only.
"""

from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import update

from ac_platform.lead_desk.errors import DeskError
from ac_platform.lead_desk.store import LeadDesk, Viewer
from ac_platform.tenancy.models import Membership
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import BASE, _organisation

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_leads_filter_sort_and_count_by_when_they_came_in(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            async with setup.sessions() as db, db.begin():
                await db.execute(
                    update(Membership)
                    .where(Membership.person_id == setup.state.person_id)
                    .values(role="owner")
                )
            tenant = setup.state.tenant_id
            seller = await seed(setup.engine, tenant_id=tenant, role="member")
            # Mid-afternoon in India, so "today" and "yesterday" never straddle midnight.
            today = datetime.now(IST).date()
            now = datetime.combine(today, time(15, 0), tzinfo=IST).astimezone(UTC)
            yesterday = now - timedelta(days=1)
            old = now - timedelta(days=10)
            owner = Viewer(person_id=setup.state.person_id, tenant_id=tenant, role="owner", name="")
            ids: dict[str, Any] = {}

            async with setup.sessions() as db, db.begin():
                desk = LeadDesk(db, owner, now=now)
                # Brought in at once, in an order unlike their arrival.
                for name, phone, received_at in (
                    ("Fictional Yesterday Lead", "9800000062", yesterday),
                    ("Fictional Old Lead", "9800000061", old),
                    ("Fictional Fresh Lead", "9800000063", None),
                ):
                    lead, outcome = await desk.ingest(
                        {"name": name, "phone": phone},
                        source="meta",
                        assign="person",
                        person_id=seller.person_id,
                        received_at=received_at,
                    )
                    assert outcome == "created" and lead is not None
                    ids[name.split()[1].lower()] = lead.id

            async with setup.sessions() as db:
                desk = LeadDesk(db, owner, now=now)

                async def names(**filters: Any) -> list[str]:
                    page = await desk.leads(
                        scope="team", stage=None, search=None, offset=0, **filters
                    )
                    return [row.name for row in page.leads]

                # Newest first by when each came in, not by when it was brought in.
                assert await names(sort="created") == [
                    "Fictional Fresh Lead",
                    "Fictional Yesterday Lead",
                    "Fictional Old Lead",
                ]
                assert await names(created="yesterday") == ["Fictional Yesterday Lead"]
                assert await names(created="today") == ["Fictional Fresh Lead"]
                assert sorted(await names(created="week")) == [
                    "Fictional Fresh Lead",
                    "Fictional Yesterday Lead",
                ]
                # A range of days, both days in.
                ten_ago = today - timedelta(days=10)
                assert await names(since=ten_ago, until=ten_ago) == ["Fictional Old Lead"]
                assert sorted(await names(since=ten_ago, until=today - timedelta(days=1))) == [
                    "Fictional Old Lead",
                    "Fictional Yesterday Lead",
                ]

                # Each row says when it was added, changed and given out.
                row = (await desk.detail(ids["old"])).lead
                assert row.received_at == old
                assert row.created_at == now
                assert row.updated_at is not None and row.assigned_at is not None

                # Leads per day: every day listed, a quiet day as 0.
                per_day = await desk.leads_per_day(since=today - timedelta(days=10), until=today)
                assert len(per_day.days) == 11 and per_day.total == 3
                counts = {item.day: item.count for item in per_day.days}
                assert counts[today] == 1
                assert counts[today - timedelta(days=1)] == 1
                assert counts[today - timedelta(days=10)] == 1
                assert counts[today - timedelta(days=5)] == 0

                # A seller sees no team counts.
                seller_view = Viewer(
                    person_id=seller.person_id, tenant_id=tenant, role="member", name=""
                )
                with pytest.raises(DeskError) as refused:
                    await LeadDesk(db, seller_view, now=now).leads_per_day(since=today, until=today)
                assert refused.value.status == 403
                with pytest.raises(DeskError):
                    await desk.leads_per_day(since=today - timedelta(days=200), until=today)

            # Over HTTP: the owner's counts, and a reversed range refused.
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                week = await client.get(
                    f"{BASE}/leads/per-day",
                    params={"since": str(today - timedelta(days=6)), "until": str(today)},
                )
                assert week.status_code == 200, week.text
                assert len(week.json()["days"]) == 7
                backwards = await client.get(
                    f"{BASE}/leads",
                    params={"scope": "team", "since": str(today), "until": str(ten_ago)},
                )
                assert backwards.status_code == 422
        finally:
            await setup.engine.dispose()

    run(exercise())
