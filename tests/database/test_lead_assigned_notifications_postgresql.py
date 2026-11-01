"""The bell's "<name> is your lead now" (owner, 27 Oct 2026: a light notice when a lead is
assigned; migration 0142), through the HTTP API on PostgreSQL.

A lead an admin gives a seller lands in that seller's bell once, urgent, opening the lead;
a lead someone takes for themselves tells nobody.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.models import AuditEvent
from ac_platform.http.product_updates import install_product_updates_http
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


def test_the_bell_reads_a_line_whose_lead_moved_on_as_history(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """QA robot 5a5fb451, 2 Nov 2026: a line that outlived its lead without being retired
    (a dev reload, or a lead removed before retiring existed) opened a lead that isn't
    there, and the 404 reached the console. The bell shows a lead line only in its own
    workspace; one whose lead is gone or someone else's now is read, opens nothing and
    isn't counted."""

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

                # The bell's own routes, mounted on an app of their own as the capture
                # reminder's test does (the harness's app doesn't carry them).
                bell_app = FastAPI()
                install_product_updates_http(
                    bell_app, settings=setup.settings, require_actor=setup.require_actor
                )

                async def bell() -> tuple[dict[str, Any], int]:
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=bell_app),
                        base_url=ORIGIN,
                        cookies={setup.settings.session_cookie_name: seller_token},
                    ) as bell_client:
                        read = await bell_client.get("/v1/notifications")
                    assert read.status_code == 200, read.text
                    lines = {
                        note["title"]: note
                        for note in read.json()["notifications"]
                        if note["kind"] == "lead_assigned"
                    }
                    return lines, read.json()["unread_count"]

                as_(setup.token)
                added = await client.post(
                    f"{BASE}/leads",
                    json={"command_id": str(uuid4()), "name": "asha fictional", "assign": "me"},
                    headers=WRITE,
                )
                assert added.status_code == 201, added.text
                lead = added.json()["lead"]
                given = await client.post(
                    f"{BASE}/leads/{lead['lead_id']}/assign",
                    json={
                        "command_id": str(uuid4()),
                        "expected_revision": lead["revision"],
                        "person_id": str(seller.person_id),
                    },
                    headers=WRITE,
                )
                assert given.status_code == 200, given.text

                as_(seller_token)
                lines, counted = await bell()
                mine = lines["Asha Fictional is your lead now"]
                assert mine["href"] == f"/leads?lead={lead['lead_id']}"
                assert mine["read"] is False and mine["urgent"] is True

                # Lines that outlived their lead, never retired: one whose lead is gone, one
                # from no workspace of this one (a line elsewhere opens nothing here), and the
                # seller's own lead given away by a way that never retired its line.
                now = datetime.now(UTC)
                async with AsyncSession(setup.engine) as db:
                    for title, tenant_id in (
                        ("Gone Fictional is your lead now", setup.state.tenant_id),
                        ("Elsewhere Fictional is your lead now", None),
                    ):
                        db.add(
                            Notification(
                                person_id=seller.person_id,
                                tenant_id=tenant_id,
                                kind="lead_assigned",
                                dedupe_key=f"lead-assigned:{uuid4()}",
                                title=title,
                                body="",
                                href=f"/leads?lead={uuid4()}",
                                urgent=True,
                                created_at=now,
                            )
                        )
                    await db.execute(
                        update(Lead)
                        .where(Lead.id == lead["lead_id"])
                        .values(owner_person_id=setup.state.person_id)
                    )
                    await db.commit()

                lines, unread = await bell()
                assert "Elsewhere Fictional is your lead now" not in lines
                for title in ("Gone Fictional is your lead now", "Asha Fictional is your lead now"):
                    assert lines[title]["read"] is True, lines[title]
                    assert lines[title]["href"] is None and lines[title]["urgent"] is False
                # The seller's own line was counted; now none of the three is.
                assert unread == counted - 1
        finally:
            await setup.engine.dispose()

    run(exercise())
