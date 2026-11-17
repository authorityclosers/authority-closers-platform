"""Archive and Bin for leads (owner, 16 Nov 2026), through the HTTP API on PostgreSQL.

Archive takes leads off every list and count and keeps them findable; Restore puts them back as
they were. Delete moves leads to the Bin (owners and admins), which only owners and admins open
and restore from; the purge deletes Bin leads for good, at once on request or after 30 days.
Each request audits once (ids and counts), a retry returns the first answer, and each lead's
history shows the move.
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, text, update

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain
from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk import deletion, shelf
from ac_platform.lead_desk.journey.http import install_journey_http
from ac_platform.lead_desk.models import Lead
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
BASE = "/v1/lead-desk"
NAMES = ("Asha Shelf", "Ravi Shelf", "Meera Shelf", "Kiran Shelf")


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_archive_bin_restore_and_purge(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            tenant = setup.state.tenant_id
            seller = await seed(setup.engine, tenant_id=tenant, role="member")
            seller_token = await _session(setup, seller)
            manager = await seed(setup.engine, tenant_id=tenant, role="manager")
            manager_token = await _session(setup, manager)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(token: str) -> None:
                    client.cookies.set(setup.settings.session_cookie_name, token)

                async def post(path: str, body: dict[str, Any]) -> httpx.Response:
                    return await client.post(f"{BASE}{path}", json=body, headers=WRITE)

                async def listed(query: str) -> set[str]:
                    page = await client.get(f"{BASE}/leads?{query}")
                    assert page.status_code == 200, page.text
                    return {row["lead_id"] for row in page.json()["leads"]}

                as_(setup.token)
                leads: list[UUID] = []
                for name in NAMES:
                    added = await post(
                        "/leads",
                        {"command_id": str(uuid4()), "name": name, "city": "Pune", "assign": "me"},
                    )
                    assert added.status_code == 201, added.text
                    leads.append(UUID(added.json()["lead"]["lead_id"]))
                a, b, c, d = leads
                everyone = {str(lead) for lead in leads}
                assert await listed("scope=team&side=inbound") == everyone

                # Sellers neither archive nor delete; managers archive but never delete.
                as_(seller_token)
                refused = await post(
                    "/leads/archive", {"command_id": str(uuid4()), "lead_ids": [str(a)]}
                )
                assert refused.status_code == 403
                assert refused.json()["detail"] == "Only owners, admins and managers archive leads."
                as_(manager_token)
                refused = await post(
                    "/leads/bin", {"command_id": str(uuid4()), "lead_ids": [str(a)]}
                )
                assert refused.status_code == 403
                assert refused.json()["detail"] == "Only owners and admins delete or restore leads."
                assert (await client.get(f"{BASE}/leads?scope=team&shelf=bin")).status_code == 403
                assert (
                    await post("/leads/archive", {"command_id": str(uuid4()), "lead_ids": []})
                ).status_code == 422
                too_many = [str(uuid4()) for _ in range(shelf.MAX_LEADS + 1)]
                assert (
                    await post("/leads/archive", {"command_id": str(uuid4()), "lead_ids": too_many})
                ).status_code == 422

                # Archive: off every list and count, found by search and the Archived list.
                first = str(uuid4())
                body = {"command_id": first, "lead_ids": [str(b), str(a), str(uuid4()), str(a)]}
                archived = await post("/leads/archive", body)
                assert archived.status_code == 200, archived.text
                assert archived.json() == {
                    "schema": "lead-desk/1",
                    "action": "archive",
                    "changed": 2,
                    "unchanged": 0,
                    "not_found": 1,
                    "lead_ids": [str(b), str(a)],
                }
                again = await post("/leads/archive", body)
                assert again.status_code == 200 and again.json() == archived.json()
                page = (await client.get(f"{BASE}/leads?scope=team&side=inbound")).json()
                assert {row["lead_id"] for row in page["leads"]} == {str(c), str(d)}
                assert page["view_counts"]["all"] == 2
                shelved = (await client.get(f"{BASE}/leads?scope=team&shelf=archived")).json()
                assert {row["lead_id"] for row in shelved["leads"]} == {str(a), str(b)}
                assert all(row["archived_at"] for row in shelved["leads"])
                assert await listed("scope=team&side=inbound&search=Asha") == {str(a)}
                assert (await client.get(f"{BASE}/leads/{a}")).status_code == 200
                # Archiving again changes nothing.
                twice = await post(
                    "/leads/archive", {"command_id": str(uuid4()), "lead_ids": [str(a)]}
                )
                assert twice.json()["changed"] == 0 and twice.json()["unchanged"] == 1

                # The Bin: owners and admins only; a binned lead opens nowhere, not even a search.
                as_(setup.token)
                binned = await post(
                    "/leads/bin", {"command_id": str(uuid4()), "lead_ids": [str(b), str(c)]}
                )
                assert binned.status_code == 200, binned.text
                assert binned.json()["changed"] == 2
                assert await listed("scope=team&shelf=bin") == {str(b), str(c)}
                assert await listed("scope=team&shelf=archived") == {str(a)}
                assert await listed("scope=team&side=inbound") == {str(d)}
                assert await listed("scope=team&search=Shelf") == {str(a), str(d)}
                # Owners and admins open a binned lead to read only (M3-A); nobody changes it.
                opened = await client.get(f"{BASE}/leads/{c}")
                assert opened.status_code == 200, opened.text
                assert opened.json()["lead"]["binned_at"] and opened.json()["worked_before"]
                noted = await post(f"/leads/{c}/notes", {"command_id": str(uuid4()), "note": "x"})
                assert noted.status_code == 404
                as_(manager_token)
                assert (await client.get(f"{BASE}/leads/{c}")).status_code == 404
                as_(setup.token)

                # Restore from the Bin puts a lead back where it was (B was archived).
                back = await post(
                    "/leads/restore",
                    {"command_id": str(uuid4()), "lead_ids": [str(b)], "from": "bin"},
                )
                assert back.status_code == 200, back.text
                assert back.json()["action"] == "restore_bin" and back.json()["changed"] == 1
                assert await listed("scope=team&shelf=archived") == {str(a), str(b)}
                as_(manager_token)
                unarchived = await post(
                    "/leads/restore",
                    {"command_id": str(uuid4()), "lead_ids": [str(a), str(b)], "from": "archive"},
                )
                assert unarchived.json()["changed"] == 2
                assert await listed("scope=team&side=inbound") == {str(a), str(b), str(d)}
                refused = await post(
                    "/leads/restore",
                    {"command_id": str(uuid4()), "lead_ids": [str(c)], "from": "bin"},
                )
                assert refused.status_code == 403

                # The lead's history shows each move.
                detail = (await client.get(f"{BASE}/leads/{a}")).json()
                moved = sorted(event["shelf"] for event in detail["events"] if event["shelf"])
                assert moved == ["archive", "restore_archive"]

                # Purge: Bin leads only, owners and admins; a lead on the desk is left alone.
                refused = await post(
                    "/leads/purge", {"command_id": str(uuid4()), "lead_ids": [str(c)]}
                )
                assert refused.status_code == 403
                as_(setup.token)
                purge = str(uuid4())
                gone = await post(
                    "/leads/purge", {"command_id": purge, "lead_ids": [str(c), str(d)]}
                )
                assert gone.status_code == 200, gone.text
                assert gone.json() == {
                    "schema": "lead-desk/1",
                    "deleted": 1,
                    "lead_ids": [str(c)],
                    "not_found": 1,
                }
                assert (await client.get(f"{BASE}/leads/{d}")).status_code == 200
                assert await listed("scope=team&shelf=bin") == set()

                # After 30 days in the Bin a lead is deleted for good by the purge job.
                assert (
                    await post("/leads/bin", {"command_id": str(uuid4()), "lead_ids": [str(d)]})
                ).json()["changed"] == 1

            now = datetime.now(UTC)
            assert await shelf.purge_due(setup.sessions, now) == 0
            async with setup.sessions() as db, db.begin():
                await db.execute(
                    update(Lead).where(Lead.id == d).values(binned_at=now - timedelta(days=31))
                )
            assert await shelf.purge_due(setup.sessions, now) == 1
            assert await shelf.purge_due(setup.sessions, now) == 0

            async with setup.sessions() as db:
                assert set(await db.scalars(select(Lead.id))) == {a, b}
                moves = (
                    await db.scalars(
                        select(AuditEvent)
                        .where(
                            AuditEvent.tenant_id == tenant,
                            AuditEvent.resource_type == shelf.AUDIT_RESOURCE,
                        )
                        .order_by(AuditEvent.sequence_no)
                    )
                ).all()
                assert [event.action for event in moves] == [
                    "lead_desk.leads.archived",
                    "lead_desk.leads.archived",
                    "lead_desk.leads.binned",
                    "lead_desk.leads.restored",
                    "lead_desk.leads.unarchived",
                    "lead_desk.leads.binned",
                ]
                assert moves[0].resource_id == first
                assert moves[0].payload["lead_ids"] == [str(b), str(a)]
                deletes = (
                    await db.scalars(
                        select(AuditEvent)
                        .where(
                            AuditEvent.tenant_id == tenant,
                            AuditEvent.action == deletion.AUDIT_ACTION,
                        )
                        .order_by(AuditEvent.sequence_no)
                    )
                ).all()
                assert [event.resource_id for event in deletes][0] == purge
                assert deletes[0].payload["lead_ids"] == [str(c)]
                assert deletes[1].actor_type == "system"
                assert deletes[1].actor_person_id is None
                assert deletes[1].payload["lead_ids"] == [str(d)]
                assert deletes[1].payload["by"] == shelf.PURGE_ACTOR
                # Ids and counts only: never a lead's name or city.
                words = json.dumps([event.payload for event in (*moves, *deletes)])
                assert not any(private in words for private in (*NAMES, "Pune"))
                assert (await verify_audit_chain(db, tenant)).valid
        finally:
            await setup.engine.dispose()

    run(exercise())


async def lock_waits(engine: Any, at_least: int) -> None:
    """Until ``at_least`` sessions wait for a row lock (the request under test is blocked)."""
    for _ in range(400):
        async with engine.connect() as connection:
            waiting = await connection.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity"
                    " WHERE wait_event_type = 'Lock' AND datname = current_database()"
                )
            )
        if waiting >= at_least:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the request never waited for the lead's lock")


def test_board_leaves_out_shelved_leads_and_purge_spares_a_lead_restored_meanwhile(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """PR 637 review: the pipeline board shows no archived or binned lead in its cards or
    counts; a purge that meets a restore in flight waits for it and leaves the lead alone."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            # The pipeline board lives in the journey routes.
            # (with an organisation's settings, as _organisation installs Leads).
            settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            install_journey_http(
                setup.app, RouteContext(settings, setup.require_actor, setup.sessions)
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)

                async def post(path: str, body: dict[str, Any]) -> httpx.Response:
                    return await client.post(f"{BASE}{path}", json=body, headers=WRITE)

                async def board() -> tuple[int, set[str]]:
                    page = await client.get(f"{BASE}/board")
                    assert page.status_code == 200, page.text
                    shown = page.json()
                    cards = {
                        card["lead_id"]
                        for group in shown["groups"]
                        for column in group["columns"]
                        for card in column["cards"]
                    }
                    assert sum(group["count"] for group in shown["groups"]) == shown["total"]
                    return shown["total"], cards

                leads: list[UUID] = []
                for name in NAMES[:3]:
                    added = await post(
                        "/leads",
                        {"command_id": str(uuid4()), "name": name, "city": "Pune", "assign": "me"},
                    )
                    assert added.status_code == 201, added.text
                    leads.append(UUID(added.json()["lead"]["lead_id"]))
                a, b, c = leads
                assert await board() == (3, {str(a), str(b), str(c)})

                # Archived and binned leads leave the board's cards and counts.
                assert (
                    await post("/leads/archive", {"command_id": str(uuid4()), "lead_ids": [str(a)]})
                ).json()["changed"] == 1
                assert (
                    await post("/leads/bin", {"command_id": str(uuid4()), "lead_ids": [str(b)]})
                ).json()["changed"] == 1
                assert await board() == (1, {str(c)})

                # A restore holds B's row when the purge arrives: the purge waits, then sees B
                # is back on the desk and deletes nothing.
                async with setup.sessions() as db, db.begin():
                    await db.execute(update(Lead).where(Lead.id == b).values(binned_at=None))
                    purging = asyncio.create_task(
                        post("/leads/purge", {"command_id": str(uuid4()), "lead_ids": [str(b)]})
                    )
                    await lock_waits(setup.engine, 1)
                    assert not purging.done()
                gone = await purging
                assert gone.status_code == 200, gone.text
                assert gone.json()["deleted"] == 0 and gone.json()["not_found"] == 1
                assert (await client.get(f"{BASE}/leads/{b}")).status_code == 200
                assert await board() == (2, {str(b), str(c)})

            async with setup.sessions() as db:
                assert set(await db.scalars(select(Lead.id))) == {a, b, c}
                deleted = await db.scalars(
                    select(AuditEvent).where(AuditEvent.action == deletion.AUDIT_ACTION)
                )
                assert not list(deleted)
        finally:
            await setup.engine.dispose()

    run(exercise())
