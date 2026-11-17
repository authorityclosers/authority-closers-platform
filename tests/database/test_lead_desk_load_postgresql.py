"""Each seller's load (owner, 16 Nov 2026: the assign sheet shows it, M1-C), through the HTTP
API on PostgreSQL: open, late, due today and untouched for 7 days per seller and for nobody's
leads, on one side; the numbers add up, archived leads are not load, and sellers can't read it."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import update

from ac_platform.lead_desk.models import Lead
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
BASE = "/v1/lead-desk"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_seller_load_adds_up_per_side(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            tenant = setup.state.tenant_id
            seller = await seed(setup.engine, tenant_id=tenant, role="member")
            seller_token = await _session(setup, seller)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(token: str) -> None:
                    client.cookies.set(setup.settings.session_cookie_name, token)

                async def post(path: str, body: dict[str, Any]) -> httpx.Response:
                    return await client.post(f"{BASE}{path}", json=body, headers=WRITE)

                as_(setup.token)
                leads: list[UUID] = []
                for index in range(4):
                    added = await post(
                        "/leads",
                        {"command_id": str(uuid4()), "name": f"Load Fictional {index}"},
                    )
                    assert added.status_code == 201, added.text
                    leads.append(UUID(added.json()["lead"]["lead_id"]))
                a, b, c, d = leads
                now = datetime.now(UTC)
                async with setup.sessions() as db, db.begin():
                    # A and B are the seller's: A an hour and more late, B untouched for 10 days.
                    await db.execute(
                        update(Lead)
                        .where(Lead.id.in_([a, b]))
                        .values(owner_person_id=seller.person_id, assigned_at=now)
                    )
                    await db.execute(
                        update(Lead)
                        .where(Lead.id == a)
                        .values(stage="follow_up", next_action_at=now - timedelta(hours=3))
                    )
                    await db.execute(
                        update(Lead)
                        .where(Lead.id == b)
                        .values(
                            stage="follow_up",
                            next_action_at=now + timedelta(days=3),
                            created_at=now - timedelta(days=10),
                            last_contact_at=None,
                        )
                    )
                    # C is nobody's; D is Cold.
                    await db.execute(
                        update(Lead)
                        .where(Lead.id == c)
                        .values(owner_person_id=None, assigned_at=None)
                    )
                    await db.execute(update(Lead).where(Lead.id == d).values(pipeline="cold"))

                read = await client.get(f"{BASE}/team/load")
                assert read.status_code == 200, read.text
                loads = read.json()
                assert loads["side"] == "inbound"
                mine = {row["person_id"]: row for row in loads["sellers"]}
                theirs = mine[str(seller.person_id)]["load"]
                assert (theirs["open"], theirs["late"], theirs["untouched_7d"]) == (2, 1, 1)
                assert theirs["by_stage"] == {"follow_up": 2}
                assert loads["unassigned"]["open"] == 1
                # The numbers add up: sellers plus nobody's are the total; stages are open.
                assert loads["totals"]["open"] == 3
                assert (
                    sum(row["load"]["open"] for row in loads["sellers"])
                    + loads["unassigned"]["open"]
                    == loads["totals"]["open"]
                )
                for row in loads["sellers"]:
                    assert sum(row["load"]["by_stage"].values()) == row["load"]["open"]
                cold = (await client.get(f"{BASE}/team/load?side=cold")).json()
                assert cold["totals"]["open"] == 1
                assert (await client.get(f"{BASE}/team/load?side=all")).status_code == 422
                assert (await client.get(f"{BASE}/team/load?x=1")).status_code == 422

                # An archived lead is no one's load.
                archived = await post(
                    "/leads/archive", {"command_id": str(uuid4()), "lead_ids": [str(a)]}
                )
                assert archived.status_code == 200, archived.text
                loads = (await client.get(f"{BASE}/team/load")).json()
                mine = {row["person_id"]: row for row in loads["sellers"]}
                assert mine[str(seller.person_id)]["load"]["open"] == 1
                assert mine[str(seller.person_id)]["load"]["late"] == 0

                as_(seller_token)
                refused = await client.get(f"{BASE}/team/load")
                assert refused.status_code == 403
        finally:
            await setup.engine.dispose()

    run(exercise())
