"""Open-lead limits on PostgreSQL (owner, 25 Oct 2026: "leads you see are capped to 50 and all
leads go beyond that, what and why? … fix this"): a seller with no rules of their own has the
organisation's default, which may be No limit; a seller's own limit may be No limit; a
manager's bulk assign and an import may go past a limit, and say so plainly; the team view
says by how much. Made-up people only."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, select, update

from ac_platform.identity.models import Person
from ac_platform.lead_desk.models import Lead
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_limits_default_none_and_going_past_said(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            fresh = await seed(
                here.setup.engine, tenant_id=here.setup.state.tenant_id, role="member"
            )
            seller = str(here.seller.person_id)
            here.as_admin()

            async def reps() -> dict[str, dict[str, Any]]:
                team = (await here.client.get(f"{BASE}/team")).json()
                return {rep["person_id"]: rep for rep in team["reps"]}

            now = await reps()
            assert now[seller]["max_open"] == 50 and now[seller]["default_cap"] is False
            assert now[str(fresh.person_id)]["max_open"] == 50
            assert now[str(fresh.person_id)]["default_cap"] is True

            # The organisation's default: No limit, for sellers with no rules of their own.
            team = (await here.client.get(f"{BASE}/team")).json()
            saved = await here.client.put(
                f"{BASE}/settings",
                json={
                    "expected_revision": team["settings"]["revision"],
                    "auto_reassign": False,
                    "reassign_minutes": 10,
                    "default_max_open": None,
                },
                headers=WRITE,
            )
            assert saved.status_code == 200, saved.text
            assert saved.json()["settings"]["default_max_open"] is None
            now = await reps()
            assert now[str(fresh.person_id)]["max_open"] is None
            assert now[seller]["max_open"] == 50

            # A seller's own limit of 1, then a manager gives them three: it goes past, said.
            limited = await here.client.put(
                f"{BASE}/team/{seller}",
                json={
                    "expected_revision": now[seller]["revision"],
                    "available": True,
                    "max_open": 1,
                },
                headers=WRITE,
            )
            assert limited.status_code == 200, limited.text
            ids = [await here.add(f"Fictional Cap {n}", f"98760 76{n:03d}") for n in range(3)]
            here.as_admin()
            async with here.setup.sessions() as db, db.begin():
                await db.execute(
                    update(Lead)
                    .where(Lead.id.in_([UUID(lead) for lead in ids]))
                    .values(owner_person_id=None, assigned_at=None)
                )
            given = await here.client.post(
                f"{BASE}/leads/bulk",
                json={
                    "command_id": str(uuid4()),
                    "lead_ids": ids,
                    "action": "assign",
                    "person_id": seller,
                },
                headers=WRITE,
            )
            assert given.status_code == 200, given.text
            assert "2 over their limit of 1" in given.json()["words"]
            assert (await reps())[seller]["over_capacity"] == 2

            # An import through an owner column (the seller's email: test people share a
            # name) goes past too, and says so.
            async with here.setup.sessions() as db:
                email = await db.scalar(
                    select(Person.email).where(Person.id == here.seller.person_id)
                )
            sheet = f"Name,Phone,Owner\nFictional Imported,98760 76100,{email}\n".encode()
            looked = await here.client.post(
                f"{BASE}/imports/preview",
                content=sheet,
                headers={
                    "Origin": WRITE["Origin"],
                    "Content-Type": "text/csv",
                    "X-File-Name": "c.csv",
                },
            )
            assert looked.status_code == 200, looked.text
            seen = looked.json()
            done = await here.client.post(
                f"{BASE}/imports",
                json={
                    "command_id": str(uuid4()),
                    "file_name": "c.csv",
                    "mapping": seen["mapping"],
                    "rows": seen["rows"],
                },
                headers=WRITE,
            )
            assert done.status_code == 200, done.text
            assert done.json()["owned"] == 1, done.text
            assert any("3 over their limit of 1" in line for line in done.json()["warnings"])

            # The seller's own No limit: nothing over.
            rev = (await reps())[seller]["revision"]
            free = await here.client.put(
                f"{BASE}/team/{seller}",
                json={"expected_revision": rev, "available": True, "max_open": None},
                headers=WRITE,
            )
            assert free.status_code == 200, free.text
            after = (await reps())[seller]
            assert after["max_open"] is None and after["over_capacity"] == 0

    run(exercise())
