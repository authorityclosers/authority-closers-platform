"""The bell's "New lead: <name>" (owner, 17 Nov 2026: Shivam, an admin, heard nothing of a
Meta lead that waited for a manager; migration 0161, lead_desk.bell.NEW), on PostgreSQL.

A lead that came in by itself and waits for someone rings every owner, admin and manager
once, urgent, opening the lead; once someone takes it, the line goes quiet for everyone.
One the lead rules gave a seller rings the owners and admins who keep New enquiry on.
A lead typed in, imported, Cold, kept as history or sent late rings nobody. Disposable
loopback PostgreSQL, fictional rows only.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.lead_desk import bell
from ac_platform.lead_desk.contracts import Reassign
from ac_platform.lead_desk.models import LeadDeskSettings, LeadRep
from ac_platform.lead_desk.store import LeadDesk, Viewer
from ac_platform.product_updates import reading
from ac_platform.product_updates.models import Notification
from ac_platform.tenancy.models import Membership
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import _setup
from tests.database.test_lead_desk_postgresql import _organisation


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


async def _lines(engine: Any, kind: str = "lead_new") -> list[Notification]:
    async with AsyncSession(engine) as db:
        return list(
            (
                await db.scalars(
                    select(Notification)
                    .where(Notification.kind == kind)
                    .order_by(Notification.created_at, Notification.person_id)
                )
            ).all()
        )


def _rep(tenant_id: UUID, person_id: UUID, *, available: bool = True) -> LeadRep:
    return LeadRep(
        tenant_id=tenant_id,
        person_id=person_id,
        revision=1,
        available=available,
        max_open=None,
        languages=[],
        areas=[],
        interests=[],
        updated_by_person_id=None,
        updated_at=datetime.now(UTC),
    )


def test_a_waiting_lead_rings_owners_admins_and_managers_until_taken(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            tenant = setup.state.tenant_id
            async with setup.sessions() as db, db.begin():
                await db.execute(
                    update(Membership)
                    .where(Membership.person_id == setup.state.person_id)
                    .values(role="owner")
                )
            admin = await seed(setup.engine, tenant_id=tenant, role="admin")
            manager = await seed(setup.engine, tenant_id=tenant, role="manager")
            seller = await seed(setup.engine, tenant_id=tenant, role="member")
            now = datetime.now(UTC)
            # The seller and the manager are not taking new leads (with no rules row, both
            # take them: managers take leads by default, owner, 19 Nov 2026).
            async with setup.sessions() as db, db.begin():
                db.add(_rep(tenant, seller.person_id, available=False))
                db.add(_rep(tenant, manager.person_id, available=False))
            system = Viewer(person_id=uuid4(), tenant_id=tenant, role="member", name="")
            owner = Viewer(
                person_id=setup.state.person_id, tenant_id=tenant, role="owner", name="O"
            )

            # No one takes new leads yet: a Meta lead waits for a manager.
            async with setup.sessions() as db, db.begin():
                lead, outcome = await LeadDesk(db, system, now=now).ingest(
                    {"name": "asha fictional", "phone": "+919800000101"},
                    source="meta",
                    source_label="Meta ad",
                    source_ref="meta:fictional-1",
                    received_at=now - timedelta(seconds=6),
                )
                assert outcome == "created" and lead is not None
                assert lead.owner_person_id is None
                waiting_id = lead.id
            lines = await _lines(setup.engine)
            assert {line.person_id for line in lines} == {
                setup.state.person_id,
                admin.person_id,
                manager.person_id,
            }
            for line in lines:
                assert line.title == "New lead: Asha Fictional"
                assert line.body.startswith("Meta ad · No one has it yet.")
                assert line.href == f"/leads?lead={waiting_id}"
                assert line.urgent is True and line.read_at is None
                assert line.tenant_id == tenant

            # The bell lists it for the admin, and it is no history while the lead waits.
            async with setup.sessions() as db:
                listed = await reading.lead_lines(db, admin.person_id, tenant)
            assert [item["kind"] for item in listed] == ["lead_new"]

            # Delivered again by Meta: a known lead rings no one twice.
            async with setup.sessions() as db, db.begin():
                _, again = await LeadDesk(db, system, now=now).ingest(
                    {"name": "asha fictional", "phone": "+919800000101"},
                    source="meta",
                    source_ref="meta:fictional-1",
                )
                assert again == "known"
            assert len(await _lines(setup.engine)) == 3

            # The owner gives it to the seller: every "New lead" goes quiet.
            async with setup.sessions() as db, db.begin():
                desk = LeadDesk(db, owner, now=now)
                detail = await desk.detail(waiting_id)
                await desk.reassign(
                    waiting_id,
                    Reassign(
                        command_id=uuid4(),
                        expected_revision=detail.lead.revision,
                        person_id=seller.person_id,
                    ),
                )
            assert all(line.read_at is not None for line in await _lines(setup.engine))
            # The seller heard "is your lead now", never "New lead".
            assert [line.person_id for line in await _lines(setup.engine, "lead_assigned")] == [
                seller.person_id
            ]

            # Typed in by hand, imported, Cold, history, or sent hours late: nobody hears.
            async with setup.sessions() as db, db.begin():
                desk = LeadDesk(db, system, now=now)
                await desk.ingest(
                    {"name": "typed fictional", "phone": "+919800000102"},
                    source="manual",
                    actor=setup.state.person_id,
                    assign="none",
                )
                await desk.ingest(
                    {"name": "file fictional", "phone": "+919800000103"},
                    source="csv",
                    batch=(uuid4(), "fictional.csv"),
                )
                await desk.ingest(
                    {"name": "cold fictional", "phone": "+919800000104"},
                    source="meta",
                    side="cold",
                )
                await desk.ingest(
                    {"name": "old fictional", "phone": "+919800000105"},
                    source="meta",
                    side="history",
                )
                await desk.ingest(
                    {"name": "late fictional", "phone": "+919800000106"},
                    source="meta",
                    received_at=now - timedelta(hours=5),
                )
            assert len(await _lines(setup.engine)) == 3
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_a_lead_the_rules_gave_rings_owners_and_admins_who_keep_new_enquiry_on(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            tenant = setup.state.tenant_id
            async with setup.sessions() as db, db.begin():
                await db.execute(
                    update(Membership)
                    .where(Membership.person_id == setup.state.person_id)
                    .values(role="owner")
                )
            admin = await seed(setup.engine, tenant_id=tenant, role="admin")
            quiet_admin = await seed(setup.engine, tenant_id=tenant, role="admin")
            manager = await seed(setup.engine, tenant_id=tenant, role="manager")
            seller = await seed(setup.engine, tenant_id=tenant, role="member")
            now = datetime.now(UTC)
            async with setup.sessions() as db, db.begin():
                db.add(_rep(tenant, seller.person_id))
                db.add(_rep(tenant, manager.person_id, available=False))  # only the seller takes it
                db.add(
                    LeadDeskSettings(
                        tenant_id=tenant,
                        revision=1,
                        config={"notify": {str(quiet_admin.person_id): {"new_enquiry": False}}},
                        updated_by_person_id=None,
                        updated_at=now,
                    )
                )
            system = Viewer(person_id=uuid4(), tenant_id=tenant, role="member", name="")
            async with setup.sessions() as db, db.begin():
                lead, _ = await LeadDesk(db, system, now=now).ingest(
                    {"name": "ravi sample", "phone": "+919800000201"},
                    source="webhook",
                )
                assert lead is not None and lead.owner_person_id == seller.person_id
                lead_id = lead.id
            lines = await _lines(setup.engine)
            assert {line.person_id for line in lines} == {setup.state.person_id, admin.person_id}
            assert manager.person_id not in {line.person_id for line in lines}
            assert all(line.title == "New lead: Ravi Sample" for line in lines)
            assert all("Given to" in line.body for line in lines)

            # Not stale while its lead is here, though it is the seller's; stale once gone.
            async with setup.sessions() as db:
                pairs = [(line.id, line.href, line.kind) for line in lines]
                assert await bell.stale(db, tenant, admin.person_id, pairs) == set()
            # A line whose lead is not in this workspace is history.
            async with setup.sessions() as db:
                missing = [(uuid4(), f"/leads?lead={uuid4()}", bell.NEW)]
                assert len(await bell.stale(db, tenant, admin.person_id, missing)) == 1
            # Deleting leads retires both kinds of line (deletion uses bell.retire).
            async with setup.sessions() as db, db.begin():
                assert await bell.retire(db, tenant, [lead_id], now) == 3
        finally:
            await setup.engine.dispose()

    run(exercise())
