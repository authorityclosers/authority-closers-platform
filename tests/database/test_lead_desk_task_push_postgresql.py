"""Task reminders on the phone, on PostgreSQL (work-memory engine, acceptance 10 and 11;
docs/product/lead-desk/work-memory-engine.md): each due reminds once, a little before it
for a call back; the lead's own due alert does not push it again; a snooze reminds once
for its new due; a task done before its time never reminds; the alert names the task."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, func, select

from ac_platform.lead_desk import push
from ac_platform.lead_desk.models import LeadTaskReminder
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_desk_tasks_postgresql import act, task
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, World, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


async def collect(here: World, at: datetime) -> list[push.Alert]:
    async with here.setup.sessions() as db, db.begin():
        return await push.collect(db, at)


async def ledger(here: World) -> int:
    async with here.setup.sessions() as db:
        return int(
            await db.scalar(
                select(func.count()).where(LeadTaskReminder.tenant_id == here.tenant_id)
            )
            or 0
        )


def test_at10_a_task_reminds_once_per_due_and_its_lead_does_not_push_it_again(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            lead_id = await here.add("Fictional Push One", "98760 61001")
            device = {"token": "fcm-token-" + "c" * 40, "app_version": "1.0.24"}
            saved = await here.client.post(f"{BASE}/devices", json=device, headers=WRITE)
            assert saved.status_code == 200, saved.text
            start = datetime.now(UTC)
            # The new lead's own alert goes first.
            await collect(here, start)

            due = start + timedelta(minutes=30)
            item = await task(here, lead_id, kind="call_back", starts_at=due.isoformat())
            assert await collect(here, due - timedelta(minutes=20)) == []
            # A call back reminds five minutes before: one alert for the lead.
            alerts = await collect(here, due - timedelta(minutes=5))
            assert [alert.leads for alert in alerts] == [[("due", UUID(lead_id))]]
            assert alerts[0].tokens == [device["token"]]
            assert await ledger(here) == 1
            # Not again: not a minute later, not at the due, not once it is overdue.
            for at in (due - timedelta(minutes=4), due, due + timedelta(minutes=2)):
                assert await collect(here, at) == [], at

            # The phone's words name the task.
            words = (await here.client.get(f"{BASE}/leads/{lead_id}/alert")).json()
            assert words["title"].startswith(f"{item['title']} at "), words

            # A snooze is a new due: it reminds once more, for that due only.
            moved = await act(here, item, "snooze", choice="1h")
            new_due = datetime.fromisoformat(moved["starts_at"])
            assert len(await collect(here, new_due - timedelta(minutes=5))) == 1
            assert await collect(here, new_due) == []
            assert await ledger(here) == 2

            # Done before its time: it never reminds.
            later_due = new_due + timedelta(hours=2)
            other = await task(here, lead_id, kind="whatsapp", starts_at=later_due.isoformat())
            await act(here, other, "done")
            await act(here, moved, "done")
            assert await collect(here, later_due) == []
            assert await ledger(here) == 2

    run(exercise())


def test_at11_a_seller_without_a_phone_gets_no_reminder_and_none_is_recorded(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            lead_id = await here.add("Fictional Push Two", "98760 61002")
            due = datetime.now(UTC) + timedelta(minutes=10)
            await task(here, lead_id, kind="email", starts_at=due.isoformat())
            assert await collect(here, due) == []
            # Recorded only when it goes: a phone added later still gets it.
            assert await ledger(here) == 0
            device = {"token": "fcm-token-" + "d" * 40, "app_version": "1.0.24"}
            saved = await here.client.post(f"{BASE}/devices", json=device, headers=WRITE)
            assert saved.status_code == 200, saved.text
            # One push for the lead: its new-lead alert and the task's go together.
            alerts = await collect(here, due + timedelta(minutes=1))
            assert [lead for alert in alerts for _, lead in alert.leads] == [UUID(lead_id)]
            assert await ledger(here) == 1

    run(exercise())
