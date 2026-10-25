"""Distribution through the HTTP API on PostgreSQL (team engine, docs/product/lead-desk/
team-engine.md, section 1 and scenarios 1 to 5): Even over three sellers gives 4, 3, 3 and a
retry changes nothing; a seller at their cap takes no more and the preview says why; by
source spreads each source over its sellers and leaves an unmapped one; closed leads never
move; each move is one history line, "Distributed: Even"; a preview names no lead."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, select, update

from ac_platform.lead_desk.models import Lead
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, World, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


async def unassign(here: World, ids: list[str], **values: Any) -> None:
    async with here.setup.sessions() as db, db.begin():
        await db.execute(
            update(Lead)
            .where(Lead.id.in_([UUID(lead) for lead in ids]))
            .values(owner_person_id=None, assigned_at=None, **values)
        )


async def owners(here: World, ids: list[str]) -> dict[str, UUID | None]:
    async with here.setup.sessions() as db:
        rows = (
            await db.execute(
                select(Lead.id, Lead.owner_person_id).where(
                    Lead.id.in_([UUID(lead) for lead in ids])
                )
            )
        ).all()
    return {str(lead): owner for lead, owner in rows}


async def cap(here: World, person: UUID, revision: int, max_open: int) -> None:
    saved = await here.client.put(
        f"{BASE}/team/{person}",
        json={"expected_revision": revision, "available": True, "max_open": max_open},
        headers=WRITE,
    )
    assert saved.status_code == 200, saved.text


def test_even_caps_by_source_closed_and_history(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            tenant = here.setup.state.tenant_id
            second = await seed(here.setup.engine, tenant_id=tenant, role="member")
            third = await seed(here.setup.engine, tenant_id=tenant, role="member")
            sellers = [here.seller.person_id, second.person_id, third.person_id]
            ids = [await here.add(f"Fictional Spread {n}", f"98760 69{n:03d}") for n in range(10)]
            await unassign(here, ids)

            # A seller may not give leads out.
            refused = await here.client.post(
                f"{BASE}/leads/distribute",
                json={"command_id": str(uuid4()), "unassigned": True, "preview": True},
                headers=WRITE,
            )
            assert refused.status_code == 403

            # 1. Even over three sellers for ten unassigned leads: 4, 3, 3. No lead names.
            here.as_admin()
            body = {
                "command_id": str(uuid4()),
                "unassigned": True,
                "rule": "even",
                "sellers": [str(person) for person in sellers],
            }
            preview = await here.client.post(
                f"{BASE}/leads/distribute", json={**body, "preview": True}, headers=WRITE
            )
            assert preview.status_code == 200, preview.text
            plan = preview.json()
            assert [seller["leads"] for seller in plan["given"]] == [4, 3, 3]
            assert plan["moved"] == 10 and plan["left"] == {}
            assert "Fictional" not in preview.text
            assert all(owner is None for owner in (await owners(here, ids)).values())

            applied = await here.client.post(
                f"{BASE}/leads/distribute", json={**body, "preview": False}, headers=WRITE
            )
            assert applied.status_code == 200, applied.text
            assert applied.json()["moved"] == 10
            placed = await owners(here, ids)
            assert sorted(
                sum(1 for owner in placed.values() if owner == person) for person in sellers
            ) == [3, 3, 4]
            # A retry of the same command returns what it did and changes nothing.
            again = await here.client.post(
                f"{BASE}/leads/distribute", json={**body, "preview": False}, headers=WRITE
            )
            assert again.status_code == 200
            assert again.json()["given"] == applied.json()["given"]
            assert await owners(here, ids) == placed

            # 5. One history line per move, with the reason.
            history = [event for event in await here.events(ids[0]) if event.kind == "reassigned"]
            assert len(history) == 1
            assert history[0].data["reason_text"] == "Distributed: Even"

            # 2. Caps: one with room for one, two full; the rest stay, and the plan says why.
            more = [await here.add(f"Fictional Cap {n}", f"98760 69{n + 50:03d}") for n in range(4)]
            await unassign(here, more)
            here.as_admin()
            await cap(here, here.seller.person_id, 1, 5)
            await cap(here, second.person_id, 0, 3)
            await cap(here, third.person_id, 0, 3)
            capped = (
                await here.client.post(
                    f"{BASE}/leads/distribute",
                    json={**body, "command_id": str(uuid4()), "preview": True},
                    headers=WRITE,
                )
            ).json()
            assert [seller["leads"] for seller in capped["given"]] == [1, 0, 0]
            assert capped["left"] == {"everyone_at_cap": 3}
            assert "cap" in capped["words"]

            # 3. By source: Facebook to the first two, Google to the third, a fair to nobody.
            await cap(here, here.seller.person_id, 2, 100)
            await cap(here, second.person_id, 1, 100)
            await cap(here, third.person_id, 1, 100)
            await unassign(here, more[:2], source_label="Facebook")
            await unassign(here, more[2:3], source_label="Google")
            await unassign(here, more[3:], source_label="Fair")
            by_source = {
                "command_id": str(uuid4()),
                "lead_ids": more,
                "rule": "by_source",
                "groups": {
                    "facebook": [str(sellers[0]), str(sellers[1])],
                    "Google": [str(sellers[2])],
                },
            }
            seen = (
                await here.client.post(
                    f"{BASE}/leads/distribute", json={**by_source, "preview": True}, headers=WRITE
                )
            ).json()
            assert seen["sources"] == {"Facebook": 2, "Fair": 1, "Google": 1}
            assert seen["left"] == {"no_seller_for_it": 1}
            done = await here.client.post(
                f"{BASE}/leads/distribute", json={**by_source, "preview": False}, headers=WRITE
            )
            assert done.status_code == 200, done.text
            now = await owners(here, more)
            assert {now[more[0]], now[more[1]]} == {sellers[0], sellers[1]}
            assert now[more[2]] == sellers[2]
            assert now[more[3]] is None

            # 4. Closed leads never move, even when chosen.
            lost = more[3]
            await unassign(here, [lost], stage="junk")
            closed = (
                await here.client.post(
                    f"{BASE}/leads/distribute",
                    json={
                        "command_id": str(uuid4()),
                        "lead_ids": [lost],
                        "sellers": [str(sellers[0])],
                        "preview": False,
                    },
                    headers=WRITE,
                )
            ).json()
            assert closed["moved"] == 0 and closed["left"] == {"closed": 1}
            assert (await owners(here, [lost]))[lost] is None

            # Neither chosen leads nor all unassigned: refused with words.
            neither = await here.client.post(
                f"{BASE}/leads/distribute",
                json={"command_id": str(uuid4()), "preview": True},
                headers=WRITE,
            )
            assert neither.status_code == 422

    run(exercise())
