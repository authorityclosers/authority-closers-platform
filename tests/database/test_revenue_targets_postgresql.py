"""Real PostgreSQL: revenue targets (owner meeting 28 Oct 2026, Dipak's idea; migration
0150). A Won lead says what it was worth, months have targets, and Home's bar reads what
it takes. Fictional leads and amounts only."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, select

from ac_platform.lead_desk.models import Lead, LeadDealAmount, LeadEvent
from ac_platform.lead_desk.revenue import IST
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, later, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_won_needs_its_amount_and_the_month_reads_against_its_targets(
    postgres_harness: Any, tmp_path: Path
):
    async def exercise():
        async with world(postgres_harness, tmp_path) as here:
            client = here.client
            month = datetime.now(IST).date().replace(day=1).isoformat()

            async def demo_done(lead: str) -> None:
                # The nine stages close a deal from a held demo only.
                booked = await here.move(
                    lead,
                    "meeting_scheduled",
                    meeting={
                        "startsAt": later(days=1),
                        "mode": "in_person",
                        "location": "Fictional office",
                    },
                )
                assert booked.status_code == 200, booked.text
                done = await here.post(
                    f"/meetings/{booked.json()['meetingId']}/done",
                    lead,
                    next_action_at=later(days=2),
                )
                assert done.status_code == 200, done.text

            # The stage sheet: Won without its amount is refused, with the words to ask.
            first = await here.add("Alex Example", "+12025550123")
            await demo_done(first)
            refused = await here.move(first, "won")
            assert refused.status_code == 422 and "Add the deal amount." in refused.text
            won = await here.move(first, "won", amount=120000)
            assert won.status_code == 200, won.text
            moved = [e for e in await here.events(first) if e.data.get("to_kind") == "won"]
            assert moved[-1].data["amount"] == 120000 and moved[-1].data["currency"] == "INR"

            # After a call: the deal value it already asked for is the amount.
            second = await here.add("Sam Example", "+12025550124")
            await demo_done(second)
            without = await here.dispose(second, connected=True, step="won")
            assert without.status_code == 422 and "Add the deal amount." in without.text
            with_value = await here.dispose(
                second, connected=True, step="won", deal_value="₹80,000"
            )
            assert with_value.status_code == 200, with_value.text
            async with here.setup.sessions() as db:
                rows = (
                    await db.scalars(
                        select(LeadDealAmount).where(LeadDealAmount.tenant_id == here.tenant_id)
                    )
                ).all()
            assert sorted(row.amount for row in rows) == [80000, 120000]
            assert {row.credited_person_id for row in rows} == {here.seller.person_id}
            assert {row.side for row in rows} == {"inbound"}

            # A lead won before amounts were asked: counted, never guessed.
            third = UUID(await here.add("Kim Example", "+12025550125"))
            async with here.setup.sessions() as db, db.begin():
                lead = await db.get(Lead, third)
                assert lead is not None
                lead.stage, lead.stage_at = "won", datetime.now(UTC)
                db.add(
                    LeadEvent(
                        id=uuid4(),
                        tenant_id=here.tenant_id,
                        lead_id=third,
                        kind="stage",
                        actor_person_id=here.seller.person_id,
                        command_id=uuid4(),
                        data={"v": 2, "from_kind": "new", "to_kind": "won", "source": "seller"},
                        created_at=datetime.now(UTC),
                    )
                )

            # No target yet: the bar has nothing to show against.
            mine = (await client.get(f"{BASE}/revenue")).json()
            assert (mine["target"], mine["won"], mine["deals"]) == (None, 200000, 2)
            assert mine["amount_not_set"] == 1 and mine["needs"] is None

            # The owner sets the month: an even split between the two people who sell.
            here.as_admin()
            set_org = await client.put(
                f"{BASE}/revenue/targets",
                json={"command_id": str(uuid4()), "month": month, "organisation": 1000000},
                headers=WRITE,
            )
            assert set_org.status_code == 200, set_org.text
            targets = set_org.json()
            assert targets["organisation"] == 1000000
            assert {line["split"] for line in targets["sellers"]} == {500000}
            here.as_seller()
            mine = (await client.get(f"{BASE}/revenue")).json()
            assert (mine["target"], mine["target_source"]) == (500000, "split")
            # Two deals of its own are too few: no average deal until the owner gives one.
            assert mine["needs"] is None

            here.as_admin()
            settings = await client.put(
                f"{BASE}/revenue/settings",
                json={
                    "expected_revision": targets["revision"],
                    "sellers_set_own": True,
                    "typical_deal": 100000,
                },
                headers=WRITE,
            )
            assert settings.status_code == 200, settings.text
            here.as_seller()
            needs = (await client.get(f"{BASE}/revenue")).json()["needs"]
            assert needs["wins"] == 3 and needs["average_deal"] == 100000
            assert needs["estimate"] is True and needs["calls_per_day"] >= 1

            # Now the seller may set their own; never the organisation's or someone else's.
            own = await client.put(
                f"{BASE}/revenue/targets",
                json={
                    "command_id": str(uuid4()),
                    "month": month,
                    "sellers": [{"person_id": str(here.seller.person_id), "amount": 600000}],
                },
                headers=WRITE,
            )
            assert own.status_code == 200, own.text
            mine = (await client.get(f"{BASE}/revenue")).json()
            assert (mine["target"], mine["target_source"]) == (600000, "own")
            org = await client.put(
                f"{BASE}/revenue/targets",
                json={"command_id": str(uuid4()), "month": month, "organisation": 1},
                headers=WRITE,
            )
            assert org.status_code == 403
            team = await client.get(f"{BASE}/revenue", params={"scope": "team"})
            assert team.status_code == 403

            # The team's month for the owner: sellers by name, never ranked.
            here.as_admin()
            team = (await client.get(f"{BASE}/revenue", params={"scope": "team"})).json()
            assert (team["target"], team["target_source"], team["won"]) == (
                1000000,
                "organisation",
                200000,
            )
            names = [line["name"] for line in team["sellers"]]
            assert names == sorted(names, key=str.lower) and len(names) == 2
            seller_line = next(
                line for line in team["sellers"] if line["person_id"] == str(here.seller.person_id)
            )
            assert (seller_line["target"], seller_line["won"]) == (600000, 200000)
            assert seller_line["amount_not_set"] == 1

            # The old Won lead gets its amount later; it now counts.
            amended = await client.put(
                f"{BASE}/leads/{third}/deal-amount",
                json={"command_id": str(uuid4()), "amount": 50000},
                headers=WRITE,
            )
            assert amended.status_code == 200, amended.text
            team = (await client.get(f"{BASE}/revenue", params={"scope": "team"})).json()
            assert (team["won"], team["deals"], team["amount_not_set"]) == (250000, 3, 0)

            # Growth: revenue by seller and by Inbound or Cold.
            split = (await client.get(f"{BASE}/revenue/breakdown", params={"days": 30})).json()
            assert (split["won"], split["deals"]) == (250000, 3)
            assert [(line["key"], line["won"]) for line in split["by_side"]] == [
                ("inbound", 250000),
                ("cold", 0),
            ]
            assert [line["won"] for line in split["by_seller"]] == [250000]
            wrong = await client.get(f"{BASE}/revenue/breakdown", params={"days": 12})
            assert wrong.status_code == 422

    run(exercise())
