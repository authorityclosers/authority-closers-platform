"""Revenue milestones on PostgreSQL (competitor teardown #27, 1 Nov 2026): the first pass only
notes where each stands; a seller who reaches half of their month's target hears it, and so do
the owners and admins, once; reaching all of it while the team reaches half is one push each,
whose words say both; a workspace with no Lead Desk settings gets its row once and its revision
never moves after; a new month starts over. Made-up
people and amounts only."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, update

from ac_platform.lead_desk import revenue_push
from ac_platform.lead_desk.models import Lead, LeadDealAmount, LeadDeskSettings
from ac_platform.lead_desk.revenue import bounds, month_of, next_month
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, World, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_amounts_read_as_homes_bar() -> None:
    assert revenue_push.short(125000) == "₹1.3 L"
    assert revenue_push.short(500000) == "₹5 L"
    assert revenue_push.short(80000) == "₹80,000"
    assert revenue_push.short(12_500_000) == "₹1.3 Cr"
    assert revenue_push.reached(249999, 500000) == 0
    assert revenue_push.reached(250000, 500000) == 50
    assert revenue_push.reached(600000, 500000) == 100
    assert revenue_push.reached(600000, None) == 0


async def pushed(here: World, now: datetime) -> list[tuple[UUID, int]]:
    async with here.setup.sessions() as db, db.begin():
        alerts = await revenue_push.collect(db, now)
    mine = [alert for alert in alerts if alert.tenant_id == here.tenant_id]
    for alert in mine:
        # A mark and a count, never a name or an amount.
        assert set(alert.data()) == {"type", "kind", "tenant", "count", "mark"}
        assert alert.data()["kind"] == "revenue" and alert.tokens
    return sorted(((alert.person_id, alert.mark) for alert in mine), key=str)


def test_revenue_milestones_reach_the_seller_and_the_owners_once(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            now = datetime.now(UTC)
            month = month_of(now)
            if month_of(now + timedelta(minutes=10)) != month:
                pytest.skip("the month ends within the test")
            name = month.strftime("%B")
            seller, admin = here.seller.person_id, here.setup.state.person_id

            for token in ("fictional-seller-phone-", "fictional-owner-phone-"):
                registered = await here.client.post(
                    f"{BASE}/devices", json={"token": token + uuid4().hex}, headers=WRITE
                )
                assert registered.status_code == 200, registered.text
                here.as_admin()
            # Even shares: ₹5 L each for the two people who sell.
            targets = await here.client.put(
                f"{BASE}/revenue/targets",
                json={
                    "command_id": str(uuid4()),
                    "month": month.isoformat(),
                    "organisation": 1000000,
                },
                headers=WRITE,
            )
            assert targets.status_code == 200, targets.text

            async def revision() -> tuple[int, dict[str, Any]]:
                async with here.setup.sessions() as db:
                    row = await db.get(LeadDeskSettings, here.tenant_id)
                    assert row is not None
                    return row.revision, dict(row.config.get(revenue_push.KEY) or {})

            async def won(amount: int, phone: str, person: UUID) -> None:
                lead = UUID(await here.add("Fictional Buyer", phone))
                async with here.setup.sessions() as db, db.begin():
                    await db.execute(
                        update(Lead).where(Lead.id == lead).values(stage="won", stage_at=now)
                    )
                    db.add(
                        LeadDealAmount(
                            id=uuid4(),
                            tenant_id=here.tenant_id,
                            lead_id=lead,
                            amount=amount,
                            currency="INR",
                            won_at=now,
                            credited_person_id=person,
                            side="inbound",
                            created_at=now,
                        )
                    )

            async def words(as_admin: bool) -> tuple[str, str, str]:
                if as_admin:
                    here.as_admin()
                else:
                    here.as_seller()
                said = await here.client.get(f"{BASE}/alert")
                assert said.status_code == 200, said.text
                found = said.json()
                return found["title"], found["body"], found["url"]

            # The first pass only notes where each stands: half of the seller's ₹5 L. A
            # workspace with a target and no Lead Desk settings yet gets its row here.
            await won(260000, "+12025550141", seller)
            assert await pushed(here, now) == []
            before, state = await revision()
            assert before == 1 and state["sent"] == {str(seller): 50}

            # All of the seller's target and half of the team's: one push each, once.
            await won(300000, "+12025550142", seller)
            assert await pushed(here, now + timedelta(minutes=2)) == sorted(
                [(seller, 100), (admin, 100)], key=str
            )
            assert await pushed(here, now + timedelta(minutes=4)) == []
            assert await words(False) == (
                f"{name} target reached",
                "₹5.6 L of ₹5 L won",
                "/dashboard",
            )
            title, body, url = await words(True)
            assert title.endswith(f" reached {name}'s target") and url == "/dashboard"
            assert body == f"₹5.6 L of ₹5 L won · The team is halfway to {name}'s target"

            # An owner who sells reaches half of their own share; the seller hears nothing.
            await won(250000, "+12025550143", admin)
            assert await pushed(here, now + timedelta(minutes=6)) == [(admin, 50)]
            assert await words(True) == (
                f"Halfway to your {name} target",
                "₹2.5 L of ₹5 L won",
                "/dashboard",
            )

            # A new month starts over, and the settings' revision never moved.
            here.as_admin()
            coming = await here.client.put(
                f"{BASE}/revenue/targets",
                json={
                    "command_id": str(uuid4()),
                    "month": next_month(month).isoformat(),
                    "organisation": 1000000,
                },
                headers=WRITE,
            )
            assert coming.status_code == 200, coming.text
            start, _ = bounds(next_month(month))
            assert await pushed(here, start + timedelta(minutes=1)) == []
            after, state = await revision()
            assert after == before
            assert state["month"] == next_month(month).isoformat() and state["sent"] == {}

    run(exercise())
