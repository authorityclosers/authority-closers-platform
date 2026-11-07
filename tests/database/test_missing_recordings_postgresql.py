"""Real PostgreSQL: today's connected lead calls with no recording two minutes after they
ended, per seller and in all (owner, 30 Oct 2026, fix 5). Fictional leads only."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, update

from ac_platform.call_ai.missing_recordings import (
    INDIA,
    calls_today,
    day_start,
    lead_names,
    missing_today,
)
from ac_platform.lead_desk.models import Lead, LeadEvent
from ac_platform.lead_desk.store import PRIVATE_CALL, LeadDesk, Viewer
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import ROOT, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_missing_calls_are_todays_connected_unrecorded_and_not_private(
    postgres_harness: Any, tmp_path: Path
):
    async def exercise():
        async with world(postgres_harness, tmp_path) as here:
            lead = UUID(await here.add("Alex Example", "+12025550123"))
            # A fixed clock (14:30 India time), never the real one: no midnight flake.
            now = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
            earlier = now - timedelta(minutes=20)
            missing, recorded, private, missed, recent, yesterday, attachment, marker = [
                uuid4() for _ in range(8)
            ]
            rows = [
                (missing, "call", {"via": "phone", "duration_seconds": 45}, earlier),
                (recorded, "call", {"via": "phone", "duration_seconds": 30}, earlier),
                (private, "call", {"via": "phone", "duration_seconds": 20}, earlier),
                (missed, "call", {"via": "phone", "direction": "missed"}, earlier),
                # Ended less than two minutes ago: its recording may still come.
                (recent, "call", {"via": "phone", "duration_seconds": 20}, now),
                (
                    yesterday,
                    "call",
                    {"via": "phone", "duration_seconds": 20},
                    day_start(now) - timedelta(minutes=5),
                ),
                (
                    attachment,
                    "call",
                    {"recording": True, "for_call": str(recorded), "submission_id": str(uuid4())},
                    earlier + timedelta(minutes=1),
                ),
                (marker, "edited", {PRIVATE_CALL: str(private), "private": True}, earlier),
            ]
            async with here.setup.sessions() as db, db.begin():
                for eid, kind, data, at in rows:
                    db.add(
                        LeadEvent(
                            id=eid,
                            tenant_id=here.tenant_id,
                            lead_id=lead,
                            kind=kind,
                            actor_person_id=here.seller.person_id,
                            command_id=uuid4(),
                            data=data,
                            created_at=at,
                        )
                    )
            async with here.setup.sessions() as db:
                everyone = await missing_today(db, tenant_id=here.tenant_id, now=now)
                mine = await missing_today(
                    db, tenant_id=here.tenant_id, now=now, person_id=here.seller.person_id
                )
                someone_else = await missing_today(
                    db, tenant_id=here.tenant_id, now=now, person_id=uuid4()
                )
            assert everyone.total == mine.total == 1
            assert mine.by_person == {here.seller.person_id: 1}
            # Its seller and lead, so a screen showing one side counts that side's (#174).
            assert everyone.calls == ((here.seller.person_id, lead),)
            assert mine.latest[here.seller.person_id] == earlier
            assert someone_else.total == 0

            # The banner reads the calls Home lists (persona QA, 31 Oct 2026): the same
            # missing call, and Home's Tried beside it; private calls and the recording
            # row itself never count.
            async with here.setup.sessions() as db:
                today = await calls_today(
                    db,
                    tenant_id=here.tenant_id,
                    person_id=here.seller.person_id,
                    role="member",
                    now=now,
                )
            assert today.missing.by_person == {here.seller.person_id: 1}
            assert today.tried == {here.seller.person_id: 3}
            # The calls themselves, by lead (teardown 13): the one missing call.
            assert [(item.event_id, item.lead_id, item.seconds) for item in today.items] == [
                (missing, lead, 45)
            ]
            async with here.setup.sessions() as db:
                names = await lead_names(db, here.tenant_id, [lead])
                assert names == {lead: "Alex Example"}
                assert await lead_names(db, here.tenant_id, []) == {}
                # One day's (the bell's reminder, ph1-27): yesterday has its own call.
                before = await calls_today(
                    db,
                    tenant_id=here.tenant_id,
                    person_id=here.seller.person_id,
                    role="member",
                    now=now,
                    day=(day_start(now) - timedelta(minutes=5)).astimezone(INDIA).date(),
                )
            assert [item.event_id for item in before.items] == [yesterday]
            assert before.tried == {here.seller.person_id: 1}

    run(exercise())


def test_each_side_counts_its_own_calls_without_a_recording(postgres_harness: Any, tmp_path: Path):
    """Owner, 4 Nov 2026 (#174 #175): Home's Inbound said 0 tried beside "11 connected
    calls without a recording", all 11 on Cold leads. Each side now counts its own."""

    async def exercise():
        async with world(postgres_harness, tmp_path) as here:
            warm = UUID(await here.add("Alex Inbound", "+12025550131"))
            cold = UUID(await here.add("Casey Cold", "+12025550132"))
            now = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
            earlier = now - timedelta(minutes=20)
            async with here.setup.sessions() as db, db.begin():
                await db.execute(update(Lead).where(Lead.id == cold).values(pipeline="cold"))
                for lead in (warm, cold, cold):
                    db.add(
                        LeadEvent(
                            id=uuid4(),
                            tenant_id=here.tenant_id,
                            lead_id=lead,
                            kind="call",
                            actor_person_id=here.seller.person_id,
                            command_id=uuid4(),
                            data={"via": "phone", "duration_seconds": 30},
                            created_at=earlier,
                        )
                    )
            async with here.setup.sessions() as db:
                desk = LeadDesk(
                    db,
                    Viewer(
                        person_id=here.seller.person_id,
                        tenant_id=here.tenant_id,
                        role="owner",
                        name="",
                    ),
                    now=now,
                )
                effort = await desk.effort(1)
            assert effort.missing_recordings == 3
            assert (effort.inbound.missing_recordings, effort.cold.missing_recordings) == (1, 2)
            assert (effort.inbound.attempted, effort.cold.attempted) == (1, 2)
            seller = next(s for s in effort.sellers if s.person_id == here.seller.person_id)
            assert (seller.inbound.missing_recordings, seller.cold.missing_recordings) == (1, 2)

    run(exercise())
