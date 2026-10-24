"""The task writer through the HTTP API on PostgreSQL (work-memory engine; the seller's
acceptance list, docs/product/lead-desk/work-memory-engine.md section 10): one task per
command, the lead's next action is its earliest open task, snoozes and history, offline
changes merged by their device time, a task follows its lead, each seller sees their own."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, select

from ac_platform.lead_desk.models import LeadTask
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import (
    BASE,
    ROOT,
    WRITE,
    World,
    later,
    world,
)


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


async def task(here: World, lead_id: str, **body: Any) -> dict[str, Any]:
    made = await here.client.post(
        f"{BASE}/leads/{lead_id}/tasks",
        json={"command_id": str(uuid4()), "kind": "call_back", **body},
        headers=WRITE,
    )
    assert made.status_code == 200, made.text
    answer: dict[str, Any] = made.json()
    return answer


async def act(here: World, item: dict[str, Any], path: str, **body: Any) -> dict[str, Any]:
    done = await here.client.post(
        f"{BASE}/tasks/{item['task_id']}/{path}",
        json={"command_id": str(uuid4()), "expected_revision": item["revision"], **body},
        headers=WRITE,
    )
    assert done.status_code == 200, done.text
    answer: dict[str, Any] = done.json()
    return answer


async def tasks_in_db(here: World) -> int:
    async with here.setup.sessions() as db:
        return int(
            await db.scalar(select(func.count()).where(LeadTask.tenant_id == here.tenant_id)) or 0
        )


def test_at15_the_next_action_is_the_earliest_open_task_and_at12_a_retry_makes_none(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            lead_id = await here.add("Fictional Task One", "98760 60001")
            later_due, sooner_due = later(hours=5), later(hours=2)
            command = str(uuid4())
            body = {"command_id": command, "kind": "whatsapp", "starts_at": later_due}
            first = await here.client.post(
                f"{BASE}/leads/{lead_id}/tasks", json=body, headers=WRITE
            )
            again = await here.client.post(
                f"{BASE}/leads/{lead_id}/tasks", json=body, headers=WRITE
            )
            assert first.status_code == again.status_code == 200
            assert first.json()["task_id"] == again.json()["task_id"]
            assert await tasks_in_db(here) == 1
            assert first.json()["title"] == "WhatsApp Fictional Task One"

            sooner = await task(here, lead_id, starts_at=sooner_due, note="Asked for 2 BHK")
            detail = await here.detail(lead_id)
            assert [item["task_id"] for item in detail["tasks"]] == [
                sooner["task_id"],
                first.json()["task_id"],
            ]
            stored = await here.stored(lead_id)
            assert stored.next_action_at == datetime.fromisoformat(sooner_due)

            # Done: the next action moves to the next task; the last one done clears it.
            await act(here, sooner, "done")
            stored = await here.stored(lead_id)
            assert stored.next_action_at == datetime.fromisoformat(later_due)
            await act(here, first.json(), "done")
            stored = await here.stored(lead_id)
            assert stored.next_action_at is None
            assert (await here.detail(lead_id))["tasks"] == []

            # Undo brings it back, and the next action with it.
            undone = await act(here, {**first.json(), "revision": 2}, "undo")
            assert undone["status"] == "open"
            stored = await here.stored(lead_id)
            assert stored.next_action_at == datetime.fromisoformat(later_due)

            # The history has a line for each.
            actions = [
                event.data["action"] for event in await here.events(lead_id) if event.kind == "task"
            ]
            assert actions == ["created", "created", "done", "done", "undone"]

    run(exercise())


def test_at09_snoozes_keep_the_first_due_and_each_shows_in_the_history(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            lead_id = await here.add("Fictional Task Two", "98760 60002")
            due = later(minutes=10)
            item = await task(here, lead_id, starts_at=due)
            once = await act(here, item, "snooze", choice="15m")
            twice = await act(here, once, "snooze", choice="1h")
            assert twice["snoozes"] == 2
            assert twice["original_due_at"] == item["starts_at"]
            assert datetime.fromisoformat(twice["starts_at"]) > datetime.fromisoformat(
                once["starts_at"]
            )
            snoozes = [
                event.data
                for event in await here.events(lead_id)
                if event.kind == "task" and event.data["action"] == "snoozed"
            ]
            assert [data["choice"] for data in snoozes] == ["15m", "1h"]
            assert snoozes[0]["from_due_at"] == datetime.fromisoformat(due).isoformat()
            done = await act(here, twice, "done")
            assert done["status"] == "done" and done["done_at"]

    run(exercise())


def test_at13_offline_changes_merge_by_their_device_time(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """Done on the phone at 15:00 (sent at 15:10), rescheduled on the computer at 15:05:
    the later change wins and the other stays in the history as superseded."""

    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            lead_id = await here.add("Fictional Task Three", "98760 60003")
            item = await task(here, lead_id, starts_at=later(hours=1))
            phone_at = datetime.now(UTC) - timedelta(minutes=10)
            computer_at = phone_at + timedelta(minutes=5)
            moved = await here.client.patch(
                f"{BASE}/tasks/{item['task_id']}",
                json={
                    "command_id": str(uuid4()),
                    "expected_revision": item["revision"],
                    "client_at": computer_at.isoformat(),
                    "starts_at": later(hours=3),
                },
                headers=WRITE,
            )
            assert moved.status_code == 200, moved.text
            late = await act(here, item, "done", client_at=phone_at.isoformat())
            assert late["status"] == "open" and late["revision"] == moved.json()["revision"]
            last = [e.data for e in await here.events(lead_id) if e.kind == "task"][-1]
            assert (last["action"], last["tried"]) == ("superseded", "done")
            # A change made later on its device goes ahead even on an old revision.
            newer = await act(
                here, item, "done", client_at=(computer_at + timedelta(minutes=1)).isoformat()
            )
            assert newer["status"] == "done"

    run(exercise())


def test_at20_each_seller_sees_their_own_tasks_and_a_task_follows_its_lead(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            lead_id = await here.add("Fictional Task Four", "98760 60004")
            overdue = await task(here, lead_id, starts_at=later(minutes=-30))
            await task(here, lead_id, kind="email", starts_at=later(days=2))
            today = await here.client.get(f"{BASE}/tasks", params={"view": "overdue"})
            body = today.json()
            assert [item["task_id"] for item in body["tasks"]] == [overdue["task_id"]]
            assert body["tasks"][0]["overdue"] is True
            assert body["counts"]["overdue"] == 1 and body["counts"]["upcoming"] == 1

            # The admin has no tasks of their own, may look at the seller's, and a seller
            # may not look at the admin's.
            here.as_admin()
            own = (await here.client.get(f"{BASE}/tasks", params={"view": "overdue"})).json()
            assert own["tasks"] == []
            seller = str(here.seller.person_id)
            theirs = await here.client.get(
                f"{BASE}/tasks", params={"view": "overdue", "person": seller}
            )
            assert len(theirs.json()["tasks"]) == 1

            # Reassigned to the admin: both open tasks go too, with a history line each.
            revision = (await here.detail(lead_id))["lead"]["revision"]
            moved = await here.client.post(
                f"{BASE}/leads/{lead_id}/assign",
                json={
                    "command_id": str(uuid4()),
                    "expected_revision": revision,
                    "person_id": str(here.setup.state.person_id),
                },
                headers=WRITE,
            )
            assert moved.status_code == 200, moved.text
            mine = (await here.client.get(f"{BASE}/tasks", params={"view": "upcoming"})).json()
            assert len(mine["tasks"]) == 1
            reassigned = [
                e.data
                for e in await here.events(lead_id)
                if e.kind == "task" and e.data["action"] == "reassigned"
            ]
            assert len(reassigned) == 2
            here.as_seller()
            refused = await here.client.get(
                f"{BASE}/tasks", params={"person": str(here.setup.state.person_id)}
            )
            assert refused.status_code == 403
            # The seller no longer reaches the lead's task.
            gone = await here.client.post(
                f"{BASE}/tasks/{overdue['task_id']}/done",
                json={"command_id": str(uuid4()), "expected_revision": 2},
                headers=WRITE,
            )
            assert gone.status_code in (403, 404)

    run(exercise())


def test_a_task_s_time_and_kind_are_checked(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            lead_id = await here.add("Fictional Task Five", "98760 60005")
            url = f"{BASE}/leads/{lead_id}/tasks"
            for wrong, status in (
                ({"kind": "fax", "starts_at": later(hours=1)}, 422),
                ({"kind": "call_back", "starts_at": later(days=400)}, 422),
                (
                    {
                        "kind": "meeting",
                        "starts_at": later(hours=2),
                        "ends_at": later(hours=1),
                    },
                    422,
                ),
            ):
                answer = await here.client.post(
                    url, json={"command_id": str(uuid4()), **wrong}, headers=WRITE
                )
                assert answer.status_code == status, answer.text
            meeting = await task(
                here,
                lead_id,
                kind="meeting",
                starts_at=later(days=1),
                ends_at=later(days=1, hours=1),
                location="Baner office",
            )
            assert meeting["title"] == "Meeting with Fictional Task Five"
            assert meeting["location"] == "Baner office" and meeting["bucket"] == "upcoming"
            assert UUID(meeting["task_id"])

    run(exercise())
