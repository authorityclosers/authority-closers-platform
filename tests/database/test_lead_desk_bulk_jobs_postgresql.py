"""Bulk changes on a frozen selection, with Undo (owner, 16 Nov 2026), through the HTTP API
on PostgreSQL: a list's filter or ids, one job per command id, each lead's own history line,
an action history, and an Undo for 30 minutes that leaves a lead changed since as it is."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain
from ac_platform.lead_desk import bulk_jobs
from ac_platform.lead_desk.models import Lead
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation
from tests.database.test_lead_desk_shelf_postgresql import lock_waits

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
BASE = "/v1/lead-desk"
NAMES = ("Asha Bulkfix", "Ravi Bulkfix", "Meera Bulkfix", "Kiran Bulkfix", "Dev Bulkfix")


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_bulk_jobs_freeze_apply_and_undo(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            tenant, owner = setup.state.tenant_id, setup.state.person_id
            seller = await seed(setup.engine, tenant_id=tenant, role="member")
            seller_token = await _session(setup, seller)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(token: str) -> None:
                    client.cookies.set(setup.settings.session_cookie_name, token)

                async def post(path: str, body: dict[str, Any]) -> httpx.Response:
                    return await client.post(f"{BASE}{path}", json=body, headers=WRITE)

                async def owners() -> dict[UUID, UUID | None]:
                    async with setup.sessions() as db:
                        rows = await db.execute(select(Lead.id, Lead.owner_person_id))
                        return {row[0]: row[1] for row in rows}

                as_(setup.token)
                leads: list[UUID] = []
                for name in NAMES:
                    added = await post(
                        "/leads",
                        {"command_id": str(uuid4()), "name": name, "city": "Pune", "assign": "me"},
                    )
                    assert added.status_code == 201, added.text
                    leads.append(UUID(added.json()["lead"]["lead_id"]))
                first = leads[0]
                matching = {"scope": "team", "side": "inbound", "search": "Bulkfix"}

                # Sellers change one lead at a time.
                as_(seller_token)
                refused = await post(
                    "/leads/bulk-jobs",
                    {
                        "command_id": str(uuid4()),
                        "filter": matching,
                        "action": "assign",
                        "person_id": str(seller.person_id),
                    },
                )
                assert refused.status_code == 403
                as_(setup.token)

                # Ids or a filter, never both or neither; a list that changed is refused.
                for body in (
                    {"command_id": str(uuid4()), "action": "archive"},
                    {
                        "command_id": str(uuid4()),
                        "action": "archive",
                        "filter": matching,
                        "lead_ids": [str(first)],
                    },
                ):
                    assert (await post("/leads/bulk-jobs", body)).status_code == 422
                changed = await post(
                    "/leads/bulk-jobs",
                    {
                        "command_id": str(uuid4()),
                        "filter": matching,
                        "expected_total": 4,
                        "action": "assign",
                        "person_id": str(seller.person_id),
                    },
                )
                assert changed.status_code == 409
                assert changed.json()["detail"].startswith("The list changed: 5 leads")

                # "All 5 matching", frozen now: given to the seller in one job.
                job = str(uuid4())
                body = {
                    "command_id": job,
                    "filter": matching,
                    "expected_total": 5,
                    "action": "assign",
                    "person_id": str(seller.person_id),
                }
                given = await post("/leads/bulk-jobs", body)
                assert given.status_code == 200, given.text
                answer = given.json()
                assert answer["job_id"] == job and answer["selection"] == "filter"
                assert (answer["selected"], answer["changed"], answer["unchanged"]) == (5, 5, 0)
                assert answer["undoable"] is True and answer["undone_at"] is None
                assert set(answer["lead_ids"]) == {str(lead) for lead in leads}
                assert answer["words"].startswith("5 leads given to ")
                again = await post("/leads/bulk-jobs", body)
                assert again.status_code == 200 and again.json() == answer
                assert set((await owners()).values()) == {seller.person_id}
                # The lead's own history shows the bulk change.
                detail = (await client.get(f"{BASE}/leads/{first}")).json()
                assert detail["events"][0]["kind"] == "reassigned"

                # The first lead moves again after the job: Undo leaves it with its new owner.
                lead = detail["lead"]
                moved = await post(
                    f"/leads/{first}/assign",
                    {
                        "command_id": str(uuid4()),
                        "expected_revision": lead["revision"],
                        "person_id": str(owner),
                    },
                )
                assert moved.status_code == 200, moved.text
                as_(seller_token)
                assert (await post(f"/leads/bulk-jobs/{job}/undo", {})).status_code == 403
                as_(setup.token)
                undone = await post(f"/leads/bulk-jobs/{job}/undo", {})
                assert undone.status_code == 200, undone.text
                assert undone.json() == {
                    "schema": "lead-desk/1",
                    "job_id": job,
                    "restored": 4,
                    "skipped": 1,
                }
                assert (await post(f"/leads/bulk-jobs/{job}/undo", {})).json() == undone.json()
                assert set((await owners()).values()) == {owner}

                # A stage move for two, then undone: back to New.
                staged = await post(
                    "/leads/bulk-jobs",
                    {
                        "command_id": str(uuid4()),
                        "lead_ids": [str(leads[1]), str(leads[2])],
                        "action": "stage",
                        "step": "interested",
                        "next_action_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
                    },
                )
                assert staged.status_code == 200, staged.text
                assert staged.json()["changed"] == 2, staged.json()
                async with setup.sessions() as db:
                    stages = set(
                        await db.scalars(
                            select(Lead.stage).where(Lead.id.in_([leads[1], leads[2]]))
                        )
                    )
                assert stages == {"interested"}
                back = await post(f"/leads/bulk-jobs/{staged.json()['job_id']}/undo", {})
                assert back.json()["restored"] == 2
                async with setup.sessions() as db:
                    stages = set(
                        await db.scalars(
                            select(Lead.stage).where(Lead.id.in_([leads[1], leads[2]]))
                        )
                    )
                assert stages == {"new"}

                # Archive by ids, then Undo: back on the desk.
                archived = await post(
                    "/leads/bulk-jobs",
                    {
                        "command_id": str(uuid4()),
                        "lead_ids": [str(leads[3]), str(leads[4]), str(uuid4())],
                        "action": "archive",
                    },
                )
                assert archived.status_code == 200, archived.text
                assert (archived.json()["changed"], archived.json()["not_found"]) == (2, 1)
                page = (await client.get(f"{BASE}/leads?scope=team&side=inbound")).json()
                assert len(page["leads"]) == 3
                restored = await post(f"/leads/bulk-jobs/{archived.json()['job_id']}/undo", {})
                assert restored.json()["restored"] == 2
                page = (await client.get(f"{BASE}/leads?scope=team&side=inbound")).json()
                assert len(page["leads"]) == 5

                # The action history, newest first; each undone, none undoable.
                history = (await client.get(f"{BASE}/leads/bulk-jobs")).json()["jobs"]
                assert [item["action"] for item in history] == ["archive", "stage", "assign"]
                assert all(item["undone_at"] and not item["undoable"] for item in history)
                assert (await client.get(f"{BASE}/leads/bulk-jobs/{job}")).json()["changed"] == 5

                # After the window Undo is closed.
                window = bulk_jobs.UNDO_MINUTES
                bulk_jobs.UNDO_MINUTES = 0  # type: ignore[misc]
                try:
                    late = await post(
                        "/leads/bulk-jobs",
                        {"command_id": str(uuid4()), "lead_ids": [str(first)], "action": "archive"},
                    )
                    assert late.json()["undoable"] is False
                    closed = await post(f"/leads/bulk-jobs/{late.json()['job_id']}/undo", {})
                    assert closed.status_code == 409
                finally:
                    bulk_jobs.UNDO_MINUTES = window  # type: ignore[misc]

            async with setup.sessions() as db:
                jobs = (
                    await db.scalars(
                        select(AuditEvent)
                        .where(
                            AuditEvent.tenant_id == tenant,
                            AuditEvent.resource_type == bulk_jobs.RESOURCE,
                        )
                        .order_by(AuditEvent.sequence_no)
                    )
                ).all()
                assert [event.action for event in jobs].count(bulk_jobs.APPLIED) == 4
                assert jobs[0].payload["selection"]["filter"]["search"] is True
                words = str([event.payload for event in jobs])
                assert not any(private in words for private in (*NAMES, "Pune", "Bulkfix"))
                assert (await verify_audit_chain(db, tenant)).valid
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_a_twin_bulk_job_waiting_for_the_locks_returns_the_first_job(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """PR 637 review: two requests with one command id both pass the first receipt check and
    wait for the same leads' locks; the second returns the first's job, with no second
    APPLIED event."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            tenant = setup.state.tenant_id
            seller = await seed(setup.engine, tenant_id=tenant, role="member")
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)

                async def post(path: str, body: dict[str, Any]) -> httpx.Response:
                    return await client.post(f"{BASE}{path}", json=body, headers=WRITE)

                leads: list[UUID] = []
                for name in NAMES[:2]:
                    added = await post(
                        "/leads",
                        {"command_id": str(uuid4()), "name": name, "city": "Pune", "assign": "me"},
                    )
                    assert added.status_code == 201, added.text
                    leads.append(UUID(added.json()["lead"]["lead_id"]))
                job = str(uuid4())
                body = {
                    "command_id": job,
                    "lead_ids": [str(lead) for lead in leads],
                    "action": "assign",
                    "person_id": str(seller.person_id),
                }
                # Someone else holds both leads: each twin passes its first check and waits.
                async with setup.sessions() as db, db.begin():
                    await db.execute(select(Lead.id).where(Lead.id.in_(leads)).with_for_update())
                    twins = [asyncio.create_task(post("/leads/bulk-jobs", body)) for _ in range(2)]
                    await lock_waits(setup.engine, 2)
                first, second = await asyncio.gather(*twins)
                assert first.status_code == 200, first.text
                assert second.status_code == 200, second.text
                assert first.json() == second.json()
                assert first.json()["changed"] == 2

            async with setup.sessions() as db:
                applied = await db.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(
                        AuditEvent.tenant_id == tenant,
                        AuditEvent.action == bulk_jobs.APPLIED,
                        AuditEvent.resource_id == job,
                    )
                )
                assert applied == 1
                owners = set(
                    await db.scalars(select(Lead.owner_person_id).where(Lead.id.in_(leads)))
                )
                assert owners == {seller.person_id}
        finally:
            await setup.engine.dispose()

    run(exercise())
