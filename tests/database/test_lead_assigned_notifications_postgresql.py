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
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.models import AuditEvent
from ac_platform.lead_desk import deletion
from ac_platform.lead_desk.models import Lead
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
                # Why, in plain words: never the lead rules' shorthand.
                assert "(fewest)" not in (bells[0].body or "")
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

                # A Cold lead given to the seller rings no bell (ph1-16, 1 Nov 2026).
                as_(setup.token)
                cold = await client.post(
                    f"{BASE}/leads",
                    json={"command_id": str(uuid4()), "name": "cold fictional", "assign": "me"},
                    headers=WRITE,
                )
                assert cold.status_code == 201, cold.text
                async with AsyncSession(setup.engine) as db:
                    await db.execute(
                        update(Lead)
                        .where(Lead.id == cold.json()["lead"]["lead_id"])
                        .values(pipeline="cold")
                    )
                    await db.commit()
                handed = await client.post(
                    f"{BASE}/leads/{cold.json()['lead']['lead_id']}/assign",
                    json={
                        "command_id": str(uuid4()),
                        "expected_revision": cold.json()["lead"]["revision"],
                        "person_id": str(seller.person_id),
                    },
                    headers=WRITE,
                )
                assert handed.status_code == 200, handed.text
                assert len(await lead_bells(seller.person_id)) == 1
                as_(seller_token)

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


def test_a_lead_now_line_goes_quiet_once_the_lead_moves_on(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """QA robot bbc3aca3, 1 Nov 2026: a deleted lead's "is your lead now" popped for two
    days and its Open lead ended on "Try again". Given to someone else or deleted, the line
    is marked read (never popped again) and stays in the bell's history."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)  # the signed-in person is an admin
            first = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            second = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            first_token = await _session(setup, first)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(token: str) -> None:
                    client.cookies.clear()
                    client.cookies.set(setup.settings.session_cookie_name, token)

                async def lines(person_id: Any) -> list[Notification]:
                    async with AsyncSession(setup.engine) as db:
                        return list(
                            (
                                await db.scalars(
                                    select(Notification).where(
                                        Notification.kind == "lead_assigned",
                                        Notification.person_id == person_id,
                                    )
                                )
                            ).all()
                        )

                async def give(lead_id: str, person_id: Any) -> None:
                    read = await client.get(f"{BASE}/leads/{lead_id}")
                    assert read.status_code == 200, read.text
                    given = await client.post(
                        f"{BASE}/leads/{lead_id}/assign",
                        json={
                            "command_id": str(uuid4()),
                            "expected_revision": read.json()["lead"]["revision"],
                            "person_id": str(person_id),
                        },
                        headers=WRITE,
                    )
                    assert given.status_code == 200, given.text

                as_(setup.token)
                added = await client.post(
                    f"{BASE}/leads",
                    json={"command_id": str(uuid4()), "name": "asha fictional", "assign": "me"},
                    headers=WRITE,
                )
                assert added.status_code == 201, added.text
                lead_id = added.json()["lead"]["lead_id"]
                await give(lead_id, first.person_id)
                [line] = await lines(first.person_id)
                assert line.read_at is None

                # Given to someone else: the first seller's line goes quiet, the second rings.
                await give(lead_id, second.person_id)
                [line] = await lines(first.person_id)
                assert line.read_at is not None
                [other] = await lines(second.person_id)
                assert other.read_at is None and other.href == f"/leads?lead={lead_id}"
                # The first seller opening the old line hears it is not theirs any more.
                as_(first_token)
                gone = await client.get(f"{BASE}/leads/{lead_id}")
                assert gone.status_code == 404, gone.text

                # Deleted: every line for it goes quiet, kept in the history, counted.
                as_(setup.token)
                deleted = await client.post(
                    f"{BASE}/leads/{lead_id}/delete",
                    json={"command_id": str(uuid4())},
                    headers=WRITE,
                )
                assert deleted.status_code == 200, deleted.text
                [other] = await lines(second.person_id)
                assert other.read_at is not None
                assert len(await lines(first.person_id)) == 1
                async with AsyncSession(setup.engine) as db:
                    audit = await db.scalar(
                        select(AuditEvent).where(
                            AuditEvent.tenant_id == setup.state.tenant_id,
                            AuditEvent.resource_type == deletion.AUDIT_RESOURCE,
                        )
                    )
                assert audit is not None
                # The second seller's line only: the first one was quiet already.
                assert audit.payload["retired"] == {"bell_lines": 1}
        finally:
            await setup.engine.dispose()

    run(exercise())
