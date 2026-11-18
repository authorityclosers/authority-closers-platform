"""A new lead reaches its seller's phone and the organisation owner's within seconds
(owner, 26 Oct 2026, dev report #3).

One lead names itself, and for the owner whose it is; several together are "5 new
leads", and from forty on "40+ new leads", counts only. A push carries ids and counts,
never a name; a lead someone typed in by hand alerts nobody new. Disposable loopback
PostgreSQL, fictional rows only.
"""

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import update

from ac_platform.lead_desk import push
from ac_platform.lead_desk.models import Lead
from ac_platform.tenancy.models import Membership
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import BASE, WRITE, _organisation


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_new_leads_reach_the_seller_and_the_owner(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            tenant = setup.state.tenant_id
            # The test organisation's maker is an admin; here they own it.
            async with setup.sessions() as db, db.begin():
                await db.execute(
                    update(Membership)
                    .where(Membership.person_id == setup.state.person_id)
                    .values(role="owner")
                )
            seller = await seed(setup.engine, tenant_id=tenant, role="member")
            seller_token = await _session(setup, seller)
            now = datetime.now(UTC)

            async def arrive(count: int, start: int, by: UUID | None = None) -> list[UUID]:
                """Leads in from a form, given to the seller by the lead rules."""
                ids = [uuid4() for _ in range(count)]
                async with setup.sessions() as db, db.begin():
                    for number, lead_id in enumerate(ids, start=start):
                        db.add(
                            Lead(
                                id=lead_id,
                                tenant_id=tenant,
                                revision=1,
                                source="webhook",
                                payload={},
                                name=f"Fictional Lead {number}",
                                stage="new",
                                attempts=0,
                                calls=0,
                                repeats=0,
                                test_data=True,
                                owner_person_id=seller.person_id,
                                assigned_at=now,
                                created_by_person_id=by,
                                created_at=now,
                                updated_at=now,
                            )
                        )
                return ids

            async def collect() -> list[push.Alert]:
                async with setup.sessions() as db, db.begin():
                    return await push.collect(db, now)

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(token: str) -> None:
                    client.cookies.set(setup.settings.session_cookie_name, token)

                for token, name in ((setup.token, "owner"), (seller_token, "seller")):
                    as_(token)
                    phone = {"token": f"fcm-{name}-" + "a" * 40, "app_version": "1.0.34"}
                    saved = await client.post(f"{BASE}/devices", json=phone, headers=WRITE)
                    assert saved.status_code == 200, saved.text

                # One lead: the seller and the owner hear of it once, by id only.
                [first] = await arrive(1, start=1)
                alerts = await collect()
                assert {alert.person_id for alert in alerts} == {
                    seller.person_id,
                    setup.state.person_id,
                }
                for alert in alerts:
                    data = alert.data()
                    assert (data["kind"], data["lead"]) == ("new", str(first))
                    assert "Fictional" not in json.dumps(data)
                assert await collect() == []
                as_(seller_token)
                mine = (await client.get(f"{BASE}/leads/{first}/alert")).json()
                assert mine["title"] == "New lead: Fictional Lead 1"
                # New leads ring on the app's Urgent work channel (owner, 17 Nov 2026).
                assert mine["urgency"] == "urgent"
                as_(setup.token)
                told = (await client.get(f"{BASE}/leads/{first}/alert")).json()
                assert told["title"].startswith("New lead for ")
                assert told["title"].endswith(": Fictional Lead 1")
                assert told["url"] == f"/leads#lead={first}"
                assert told["urgency"] == "urgent"

                # Four more together: one alert each, "5 new leads", nobody named.
                await arrive(4, start=2)
                alerts = await collect()
                assert sorted(alert.data()["alerts"] for alert in alerts) == ["4", "4"]
                assert {alert.data()["kind"] for alert in alerts} == {"many"}
                for token in (setup.token, seller_token):
                    as_(token)
                    words = (await client.get(f"{BASE}/alert")).json()
                    assert (words["title"], words["url"]) == ("5 new leads", "/leads")
                    assert "Fictional" not in words["body"]

                # Forty more: "40+ new leads".
                await arrive(40, start=6)
                assert len(await collect()) == 2
                as_(setup.token)
                assert (await client.get(f"{BASE}/alert")).json()["title"] == "40+ new leads"

                # A lead the seller typed in for themselves alerts nobody.
                await arrive(1, start=99, by=seller.person_id)
                assert await collect() == []
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_admins_hear_and_a_lead_nobody_got_waits_for_them(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """Wise Life, 17 Nov 2026: every seller was at their open-lead limit, so new Meta leads
    went to nobody and told nobody, and an admin never heard of any new lead. Now the owner
    and the admins hear of each new lead; one nobody got reaches them as "New lead waiting",
    once; its seller hears when it is given out; a lead held for work hours stays quiet."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            tenant = setup.state.tenant_id
            async with setup.sessions() as db, db.begin():
                await db.execute(
                    update(Membership)
                    .where(Membership.person_id == setup.state.person_id)
                    .values(role="owner")
                )
            admin = await seed(setup.engine, tenant_id=tenant, role="admin")
            seller = await seed(setup.engine, tenant_id=tenant, role="member")
            admin_token = await _session(setup, admin)
            seller_token = await _session(setup, seller)
            now = datetime.now(UTC)

            async def arrive(name: str, *, owner: UUID | None, reason: str | None) -> UUID:
                lead_id = uuid4()
                async with setup.sessions() as db, db.begin():
                    db.add(
                        Lead(
                            id=lead_id,
                            tenant_id=tenant,
                            revision=1,
                            source="meta",
                            payload={},
                            name=name,
                            stage="new",
                            attempts=0,
                            calls=0,
                            repeats=0,
                            test_data=True,
                            owner_person_id=owner,
                            owner_reason=reason,
                            assigned_at=now if owner else None,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                return lead_id

            async def heard(at: datetime) -> dict[UUID, list[tuple[str, str]]]:
                async with setup.sessions() as db, db.begin():
                    alerts = await push.collect(db, at)
                return {a.person_id: [(kind, str(lead)) for kind, lead in a.leads] for a in alerts}

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(token: str) -> None:
                    client.cookies.set(setup.settings.session_cookie_name, token)

                for token, name in (
                    (setup.token, "owner"),
                    (admin_token, "admin"),
                    (seller_token, "seller"),
                ):
                    as_(token)
                    phone = {"token": f"fcm-{name}-" + "b" * 40, "app_version": "1.0.126"}
                    saved = await client.post(f"{BASE}/devices", json=phone, headers=WRITE)
                    assert saved.status_code == 200, saved.text

                # A lead the rules gave the seller: the seller, the owner and the admin.
                given = await arrive("Fictional Given", owner=seller.person_id, reason=None)
                assert await heard(now) == {
                    person: [("new", str(given))]
                    for person in (seller.person_id, setup.state.person_id, admin.person_id)
                }
                as_(admin_token)
                told = (await client.get(f"{BASE}/leads/{given}/alert")).json()
                assert told["title"].startswith("New lead for ")

                # A lead nobody got: the owner and the admin, once, never the seller.
                waits = await arrive(
                    "Fictional Waiting",
                    owner=None,
                    reason="Everyone available is at their open-lead limit;"
                    " it waits for a manager.",
                )
                assert await heard(now) == {
                    person: [("new", str(waits))]
                    for person in (setup.state.person_id, admin.person_id)
                }
                assert await heard(now) == {}
                as_(admin_token)
                words = (await client.get(f"{BASE}/leads/{waits}/alert")).json()
                assert words["title"] == "New lead waiting: Fictional Waiting"
                assert "tap to assign" in words["body"]
                assert words["urgency"] == "urgent"
                # The time it came in, as a clock time and how long ago (owner, 17 Nov 2026).
                assert re.search(r"\d{1,2}:\d{2} (AM|PM), ", words["body"])
                as_(seller_token)
                hidden = await client.get(f"{BASE}/leads/{waits}/alert")
                assert hidden.status_code != 200

                # Given out a moment later: now its seller hears of it.
                later = now + timedelta(seconds=2)
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(Lead)
                        .where(Lead.id == waits)
                        .values(owner_person_id=seller.person_id, assigned_at=later)
                    )
                assert str(waits) in str((await heard(later)).get(seller.person_id))

                # Held for work hours: it goes to a seller at opening; nobody hears now.
                await arrive(
                    "Fictional Night",
                    owner=None,
                    reason="Outside work hours. It goes to a seller at 10:00 AM.",
                )
                assert await heard(later) == {}
        finally:
            await setup.engine.dispose()

    run(exercise())
