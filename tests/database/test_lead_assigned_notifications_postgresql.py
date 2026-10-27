"""The bell's "<name> is your lead now" (owner, 27 Oct 2026: a light notice when a lead is
assigned; migration 0142), through the HTTP API on PostgreSQL.

A lead an admin gives a seller lands in that seller's bell once, urgent, opening the lead;
a lead someone takes for themselves tells nobody.
"""

from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.product_updates.models import Notification
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


def test_a_lead_given_to_a_seller_rings_their_bell_once(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)  # the signed-in person is an admin
            seller = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            seller_token = await _session(setup, seller)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(token: str) -> None:
                    client.cookies.clear()
                    client.cookies.set(setup.settings.session_cookie_name, token)

                async def lead_bells(person_id: Any) -> list[Notification]:
                    async with AsyncSession(setup.engine) as db:
                        return list(
                            (
                                await db.scalars(
                                    select(Notification)
                                    .where(
                                        Notification.kind == "lead_assigned",
                                        Notification.person_id == person_id,
                                    )
                                    .order_by(Notification.created_at)
                                )
                            ).all()
                        )

                as_(setup.token)
                added = await client.post(
                    f"{BASE}/leads",
                    json={"command_id": str(uuid4()), "name": "asha fictional", "assign": "me"},
                    headers=WRITE,
                )
                assert added.status_code == 201, added.text
                lead = added.json()["lead"]
                # Taken by the admin themself: nobody is told.
                assert await lead_bells(setup.state.person_id) == []

                command = {
                    "command_id": str(uuid4()),
                    "expected_revision": lead["revision"],
                    "person_id": str(seller.person_id),
                }
                given = await client.post(
                    f"{BASE}/leads/{lead['lead_id']}/assign", json=command, headers=WRITE
                )
                assert given.status_code == 200, given.text
                # The same request again changes nothing and tells nobody twice.
                again = await client.post(
                    f"{BASE}/leads/{lead['lead_id']}/assign", json=command, headers=WRITE
                )
                assert again.status_code == 200, again.text
                assert await lead_bells(setup.state.person_id) == []

                as_(seller_token)
                bells = await lead_bells(seller.person_id)
                assert len(bells) == 1, bells
                assert bells[0].title == "Asha Fictional is your lead now"
                assert bells[0].href == f"/leads?lead={lead['lead_id']}"
                assert bells[0].urgent is True
                assert bells[0].read_at is None
                assert str(bells[0].tenant_id) == str(setup.state.tenant_id)

                # The seller's own lead tells nobody.
                own = await client.post(
                    f"{BASE}/leads",
                    json={"command_id": str(uuid4()), "name": "ravi sample", "assign": "me"},
                    headers=WRITE,
                )
                assert own.status_code == 201, own.text
                assert len(await lead_bells(seller.person_id)) == 1

                # Team today (Home's Team view) is for those who see the team.
                refused = await client.get(f"{BASE}/activity", params={"team": "1"})
                assert refused.status_code == 403, refused.text

                as_(setup.token)
                day = await client.get(f"{BASE}/activity", params={"day": "today", "team": "1"})
                assert day.status_code == 200, day.text
                items = day.json()["items"]
                handed = [
                    item
                    for item in items
                    if item["lead_id"] == lead["lead_id"]
                    and item["event"]["kind"] in {"assigned", "reassigned"}
                    and item["event"]["owner_name"]
                ]
                assert handed, items
                # Everyone's work, not only the admin's: the seller's own lead is there too.
                assert any(item["lead_name"] == "ravi sample" for item in items), items
        finally:
            await setup.engine.dispose()

    run(exercise())
