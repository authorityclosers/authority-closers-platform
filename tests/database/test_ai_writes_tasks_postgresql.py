"""Tasks for apps on PostgreSQL (API gap 8, 15 Nov 2026; ai-writes.md: leads:tasks also marks a
task done).

An organisation's key lists open tasks as the app's Tasks list shows them
(``GET /v1/api/tasks``), marks a task on a lead done and snoozes one, each behind the AI-write
guardrails (the owner's task switch, ``leads:tasks``, a retry changes nothing, the ledger
names the task), and Undo reopens a task or puts its due back. A task of your own stays in
the app; a task that isn't open can't be marked. Fictional rows only.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from ac_platform.http.routes import RouteContext
from ac_platform.integrations.api_http import install_integrations_api
from ac_platform.integrations.http import install_integrations_http
from ac_platform.integrations.models import IntegrationWrite
from ac_platform.lead_desk.models import LeadTask
from ac_platform.tenancy.models import Membership
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


async def _task(setup: Any, task_id: str) -> LeadTask:
    async with setup.sessions() as db:
        task = await db.get(LeadTask, UUID(task_id))
        assert task is not None
        return task


def test_an_app_lists_marks_done_and_snoozes_tasks_and_undo_puts_them_back(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            context = RouteContext(setup.settings, setup.require_actor, setup.sessions)
            install_integrations_http(setup.app, context)
            install_integrations_api(setup.app, context)
            transport = httpx.ASGITransport(app=setup.app)
            async with (
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as person,
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as app,
            ):
                person.cookies.set(setup.settings.session_cookie_name, setup.token)
                made = await person.post(
                    "/v1/sales-xray/integrations/keys",
                    headers=WRITE,
                    json={
                        "name": "Fictional planner",
                        "scopes": ["leads:read", "leads:write", "leads:tasks"],
                    },
                )
                assert made.status_code == 200, made.text
                bearer = {"Authorization": f"Bearer {made.json()['key']}"}
                lead = (
                    await app.post(
                        "/v1/api/leads", headers=bearer, json={"name": "Meera Joshi (test)"}
                    )
                ).json()["id"]
                due = (datetime.now(UTC) + timedelta(days=3)).replace(microsecond=0)
                added = await app.post(
                    f"/v1/api/leads/{lead}/tasks",
                    headers=bearer,
                    json={
                        "kind": "whatsapp",
                        "due": due.isoformat(),
                        "title": "Send the brochure",
                        "request_id": "req-task-0001",
                    },
                )
                assert added.status_code == 201, added.text
                task_id = added.json()["task_id"]
                # The task's owner is the lead's; give an unassigned lead's task a person.
                async with setup.sessions() as db, db.begin():
                    row = await db.get(LeadTask, UUID(task_id))
                    assert row is not None
                    if row.owner_person_id is None:
                        row.owner_person_id = await db.scalar(
                            select(Membership.person_id)
                            .where(Membership.tenant_id == row.tenant_id)
                            .limit(1)
                        )
                    owner = row.owner_person_id

                listed = await app.get(
                    "/v1/api/tasks",
                    headers=bearer,
                    params={"view": "upcoming", "person": str(owner)},
                )
                assert listed.status_code == 200, listed.text
                assert task_id in {item["task_id"] for item in listed.json()["tasks"]}
                assert set(listed.json()["counts"]) == {"overdue", "today", "upcoming"}
                wrong = await app.get("/v1/api/tasks", headers=bearer, params={"view": "someday"})
                assert wrong.status_code == 422

                done_path = f"/v1/api/tasks/{task_id}/done"
                preview = await app.post(
                    done_path, headers=bearer, json={"request_id": "req-done-0000", "preview": True}
                )
                assert preview.json()["would_change"] == {"status": "done"}
                assert (await _task(setup, task_id)).status == "open"
                first = await app.post(
                    done_path, headers=bearer, json={"request_id": "req-done-0001"}
                )
                assert first.status_code == 200, first.text
                assert first.json()["action"] == "task"
                assert first.json()["task_change"] == "done"
                assert first.json()["task_id"] == task_id
                again = await app.post(
                    done_path, headers=bearer, json={"request_id": "req-done-0001"}
                )
                assert again.json()["replayed"] is True
                assert (await _task(setup, task_id)).status == "done"
                closed = await app.post(
                    done_path, headers=bearer, json={"request_id": "req-done-0002"}
                )
                assert closed.status_code == 409 and closed.json()["error"]["code"] == "not_open"

                # Undo reopens it.
                undone = await app.post(
                    f"/v1/api/changes/{first.json()['change_id']}/undo", headers=bearer, json={}
                )
                assert undone.status_code == 200, undone.text
                assert (await _task(setup, task_id)).status == "open"

                # Snooze moves its due later; undo puts it back.
                before = (await _task(setup, task_id)).starts_at
                snoozed = await app.post(
                    f"/v1/api/tasks/{task_id}/snooze",
                    headers=bearer,
                    json={"choice": "week", "request_id": "req-snooze-0001"},
                )
                assert snoozed.status_code == 200, snoozed.text
                assert (await _task(setup, task_id)).starts_at > before
                back = await app.post(
                    f"/v1/api/changes/{snoozed.json()['change_id']}/undo", headers=bearer, json={}
                )
                assert back.status_code == 200, back.text
                assert (await _task(setup, task_id)).starts_at == before

                # A person's later change wins over an undo.
                later = await app.post(
                    f"/v1/api/tasks/{task_id}/snooze",
                    headers=bearer,
                    json={"choice": "tomorrow", "request_id": "req-snooze-0002"},
                )
                assert later.status_code == 200, later.text
                current = await _task(setup, task_id)
                touched = await person.post(
                    f"/v1/lead-desk/tasks/{task_id}/done",
                    headers=WRITE,
                    json={"command_id": str(uuid4()), "expected_revision": current.revision},
                )
                assert touched.status_code == 200, touched.text
                late = await app.post(
                    f"/v1/api/changes/{later.json()['change_id']}/undo", headers=bearer, json={}
                )
                assert late.status_code == 409
                assert late.json()["error"]["code"] == "changed_since"

                # The ledger keeps them as task writes on this task, by the field each
                # changed, never the text; the task's adding names its kind.
                async with setup.sessions() as db:
                    rows = (
                        await db.scalars(
                            select(IntegrationWrite).where(IntegrationWrite.action == "task")
                        )
                    ).all()
                assert {str(row.task_id) for row in rows} == {task_id}
                kinds = [tuple(row.fields) for row in rows]
                assert kinds.count(("status",)) == 1 and kinds.count(("starts_at",)) == 2
                assert sum("kind" in fields for fields in kinds) == 1
                listed_changes = (await app.get("/v1/api/changes", headers=bearer)).json()
                assert {item.get("task_change") for item in listed_changes["changes"]} == {
                    "added",
                    "done",
                    "snoozed",
                }

                # A task of your own stays in the app; one that doesn't exist is missing.
                own = await person.post(
                    "/v1/lead-desk/tasks",
                    headers=WRITE,
                    json={
                        "command_id": str(uuid4()),
                        "kind": "other",
                        "starts_at": due.isoformat(),
                        "title": "Plan the week",
                    },
                )
                assert own.status_code == 200, own.text
                mine = await app.post(
                    f"/v1/api/tasks/{own.json()['task_id']}/done",
                    headers=bearer,
                    json={"request_id": "req-done-0003"},
                )
                assert mine.status_code == 422 and mine.json()["error"]["code"] == "own_task"
                missing = await app.post(
                    f"/v1/api/tasks/{uuid4()}/done",
                    headers=bearer,
                    json={"request_id": "req-done-0004"},
                )
                assert missing.status_code == 404
        finally:
            await setup.engine.dispose()

    run(exercise())
