"""When a lead reached the business (migration 0139; owner, 26 Oct 2026, dev report #7: an
old Meta lead brought in later showed as a new lead).

A lead its source says was sent ten days ago is brought in today: it keeps that time, it
doesn't count as come in this week, and it doesn't wake the owner; its seller still hears
it was given to them. A time ahead of now is taken as now. Disposable loopback
PostgreSQL, fictional rows only.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from sqlalchemy import select, update

from ac_platform.lead_desk import push
from ac_platform.lead_desk.models import Lead
from ac_platform.lead_desk.store import LeadDesk, Viewer
from ac_platform.tenancy.models import Membership
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import BASE, WRITE, _organisation


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_an_old_lead_brought_in_today_is_not_new(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            # The test organisation's maker is an admin; here they own it.
            async with setup.sessions() as db, db.begin():
                await db.execute(
                    update(Membership)
                    .where(Membership.person_id == setup.state.person_id)
                    .values(role="owner")
                )
            tenant = setup.state.tenant_id
            seller = await seed(setup.engine, tenant_id=tenant, role="member")
            seller_token = await _session(setup, seller)
            now = datetime.now(UTC)
            sent = now - timedelta(days=10)
            owner = Viewer(person_id=setup.state.person_id, tenant_id=tenant, role="owner", name="")

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                for token, name in ((setup.token, "owner"), (seller_token, "seller")):
                    client.cookies.set(setup.settings.session_cookie_name, token)
                    phone = {"token": f"fcm-{name}-" + "b" * 40, "app_version": "1.0.34"}
                    saved = await client.post(f"{BASE}/devices", json=phone, headers=WRITE)
                    assert saved.status_code == 200, saved.text

            async with setup.sessions() as db, db.begin():
                desk = LeadDesk(db, owner, now=now)
                for record, received_at in (
                    ({"name": "Fictional Old Lead", "phone": "9800000051"}, sent),
                    ({"name": "Fictional Fresh Lead", "phone": "9800000052"}, None),
                    (
                        {"name": "Fictional Early Lead", "phone": "9800000053"},
                        now + timedelta(hours=3),
                    ),
                ):
                    lead, outcome = await desk.ingest(
                        record,
                        source="meta",
                        assign="person",
                        person_id=seller.person_id,
                        received_at=received_at,
                    )
                    assert outcome == "created" and lead is not None
                old, fresh, early = [
                    (await desk.detail(lead_id)).lead for lead_id in await _ids(db, tenant)
                ]
            assert old.received_at == sent and fresh.received_at is None
            assert early.received_at == now  # a time ahead of now is taken as now

            # This week's new leads count the two that came in now, not the old one.
            async with setup.sessions() as db:
                week = await LeadDesk(db, owner, now=now).performance(7)
            assert week.current.new_leads == 2

            # The seller hears of all three; the owner only of the two just in.
            async with setup.sessions() as db, db.begin():
                alerts = {alert.person_id: alert for alert in await push.collect(db, now)}
            assert alerts[seller.person_id].data()["alerts"] == "3"
            assert alerts[setup.state.person_id].data()["alerts"] == "2"
        finally:
            await setup.engine.dispose()

    run(exercise())


async def _ids(db: Any, tenant: Any) -> list[Any]:
    """The organisation's leads, by their fictional numbers."""
    rows = await db.scalars(select(Lead.id).where(Lead.tenant_id == tenant).order_by(Lead.phone))
    return list(rows.all())
