"""AI writes, first slice, on PostgreSQL (owner order, 25 Oct 2026; docs/product/ai-writes.md).

An API key adds notes and tasks to a lead through /v1/api, behind the guardrails: a
retried request changes nothing, a request id is never reused for another change, only
the allowed fields are taken, the owner's switch pauses writes while reading goes on,
the caps hold, and every change shows which key sent it, is in the ledger and the audit
log, and can be undone for 7 days without deleting anything. A person's later change to
a task wins over an undo.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from ac_platform.audit.models import AuditEvent
from ac_platform.http.routes import RouteContext
from ac_platform.integrations import write_policy
from ac_platform.integrations.api_http import install_integrations_api
from ac_platform.integrations.http import install_integrations_http
from ac_platform.integrations.models import IntegrationWrite
from ac_platform.lead_desk.models import LeadEvent, LeadTask
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
DESK = "/v1/lead-desk"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def _due(hours: int = 20) -> str:
    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat()


def test_notes_and_tasks_from_an_api_key_behind_the_guardrails(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
                        "name": "Fictional assistant",
                        "scopes": ["leads:read", "leads:write", "leads:notes", "leads:tasks"],
                    },
                )
                assert made.status_code == 200, made.text
                key, prefix = made.json()["key"], made.json()["prefix"]
                bearer = {"Authorization": f"Bearer {key}"}
                added = await app.post(
                    "/v1/api/leads", headers=bearer, json={"name": "Fictional AI Lead"}
                )
                other = await app.post(
                    "/v1/api/leads", headers=bearer, json={"name": "Fictional Other Lead"}
                )
                assert added.status_code == 201, added.text
                lead, other_lead = added.json()["id"], other.json()["id"]

                # A note: applied once, a retry changes nothing.
                body = {"note": "Wants​ a demo on Monday.", "request_id": "req-note-0001"}
                first = await app.post(f"/v1/api/leads/{lead}/notes", headers=bearer, json=body)
                assert first.status_code == 201, first.text
                note = first.json()
                assert note["status"] == "applied" and note["via"] == f"API key {prefix}"
                again = await app.post(f"/v1/api/leads/{lead}/notes", headers=bearer, json=body)
                assert again.status_code == 200 and again.json()["replayed"] is True
                assert again.json()["change_id"] == note["change_id"]
                reused = await app.post(
                    f"/v1/api/leads/{other_lead}/notes", headers=bearer, json=body
                )
                assert reused.status_code == 409
                assert reused.json()["error"]["code"] == "request_reused"
                # Only the fields a note takes.
                extra = await app.post(
                    f"/v1/api/leads/{lead}/notes",
                    headers=bearer,
                    json={**body, "request_id": "req-note-0002", "stage": "won"},
                )
                assert extra.status_code == 422
                # A preview changes nothing.
                preview = await app.post(
                    f"/v1/api/leads/{lead}/notes",
                    headers=bearer,
                    json={"note": "Maybe", "request_id": "req-note-0003", "preview": True},
                )
                assert preview.status_code == 200 and preview.json()["preview"] is True

                # A task, for the lead's owner, marked as from the assistant.
                task = await app.post(
                    f"/v1/api/leads/{lead}/tasks",
                    headers=bearer,
                    json={"kind": "call_back", "due": _due(), "request_id": "req-task-0001"},
                )
                assert task.status_code == 201, task.text
                second = await app.post(
                    f"/v1/api/leads/{lead}/tasks",
                    headers=bearer,
                    json={"kind": "whatsapp", "due": _due(30), "request_id": "req-task-0002"},
                )
                assert second.status_code == 201, second.text

                # The lead's history: which key sent each, and Undo while it may.
                detail = (await person.get(f"{DESK}/leads/{lead}")).json()
                from_app = [event for event in detail["events"] if event.get("change_id")]
                assert {event["kind"] for event in from_app} == {"note", "task"}
                assert all(event["app_label"] == f"API key {prefix}" for event in from_app)
                assert all(event["can_undo"] for event in from_app)
                noted = next(event for event in from_app if event["kind"] == "note")
                assert noted["note"] == "Wants a demo on Monday."  # invisible characters gone

                # The ledger and the audit log: one row each per change, no text.
                async with setup.sessions() as db:
                    rows = (await db.scalars(select(IntegrationWrite))).all()
                    assert sorted(row.action for row in rows) == ["note", "task", "task"]
                    assert all(row.via == "key" and row.key_id for row in rows)
                    audit = (
                        await db.scalars(
                            select(AuditEvent).where(AuditEvent.action.like("ai_write.%"))
                        )
                    ).all()
                    assert sorted(event.action for event in audit) == [
                        "ai_write.note",
                        "ai_write.task",
                        "ai_write.task",
                    ]
                    assert "demo" not in str([event.payload for event in audit])
                    made = {UUID(task.json()["task_id"]), UUID(second.json()["task_id"])}
                    tasks = (await db.scalars(select(LeadTask).where(LeadTask.id.in_(made)))).all()
                    assert [item.source for item in tasks] == ["assistant", "assistant"]

                # Undo the note through the API: it stops showing; nothing is deleted.
                undo = await app.post(
                    f"/v1/api/changes/{note['change_id']}/undo", headers=bearer, json={}
                )
                assert undo.status_code == 200, undo.text
                assert undo.json()["status"] == "undone"
                twice = await app.post(
                    f"/v1/api/changes/{note['change_id']}/undo", headers=bearer, json={}
                )
                assert twice.status_code == 200 and twice.json()["replayed"] is True
                detail = (await person.get(f"{DESK}/leads/{lead}")).json()
                assert not [e for e in detail["events"] if e["kind"] == "note"]
                notes = (await person.get(f"{DESK}/notes")).json()
                assert not [item for item in notes["items"] if item["lead_id"] == lead]
                async with setup.sessions() as db:
                    kept = (
                        await db.scalars(select(LeadEvent).where(LeadEvent.kind == "note"))
                    ).all()
                    assert len(kept) == 1  # the history keeps the note

                # Undo a task in the app: it is cancelled. A task someone has since
                # changed is not undone: the person's change wins.
                changes = (await person.get(f"{DESK}/ai-changes")).json()["changes"]
                by_task = {item["change_id"]: item for item in changes if item["action"] == "task"}
                assert set(by_task) == {task.json()["change_id"], second.json()["change_id"]}
                undone = await person.post(
                    f"{DESK}/ai-changes/{task.json()['change_id']}/undo", headers=WRITE
                )
                assert undone.status_code == 200, undone.text
                done = await person.post(
                    f"{DESK}/tasks/{second.json()['task_id']}/done",
                    headers=WRITE,
                    json={"command_id": str(uuid4()), "expected_revision": 1},
                )
                assert done.status_code == 200, done.text
                late = await app.post(
                    f"/v1/api/changes/{second.json()['change_id']}/undo", headers=bearer, json={}
                )
                assert late.status_code == 409
                assert late.json()["error"]["code"] == "changed_since"
                async with setup.sessions() as db:
                    first_task = await db.get(LeadTask, UUID(task.json()["task_id"]))
                    assert first_task is not None and first_task.status == "cancelled"

                # The owner's switch pauses changes from apps; reading goes on.
                switch = (await person.get(f"{DESK}/ai-writes")).json()
                assert switch["paused"] is False and switch["note"] is True
                paused = await person.put(
                    f"{DESK}/ai-writes",
                    headers=WRITE,
                    json={
                        "expected_revision": switch["revision"],
                        "paused": True,
                        "note": True,
                        "task": True,
                        "outcome": True,
                    },
                )
                assert paused.status_code == 200, paused.text
                refused = await app.post(
                    f"/v1/api/leads/{lead}/notes",
                    headers=bearer,
                    json={"note": "Again", "request_id": "req-note-0004"},
                )
                assert refused.status_code == 403
                assert refused.json()["error"]["code"] == "writes_paused"
                assert (await app.get(f"/v1/api/leads/{lead}", headers=bearer)).status_code == 200
                resumed = await person.put(
                    f"{DESK}/ai-writes",
                    headers=WRITE,
                    json={
                        "expected_revision": paused.json()["revision"],
                        "paused": False,
                        "note": True,
                        "task": True,
                        "outcome": True,
                    },
                )
                assert resumed.status_code == 200, resumed.text

                # The caps hold (a low one here, so the test stays quick).
                monkeypatch.setitem(write_policy.PER_LEAD, "note", 2)
                answers = [
                    await app.post(
                        f"/v1/api/leads/{other_lead}/notes",
                        headers=bearer,
                        json={"note": f"Note {n}", "request_id": f"req-cap-000{n}"},
                    )
                    for n in range(3)
                ]
                assert [answer.status_code for answer in answers] == [201, 201, 429]
                assert answers[2].json()["error"]["code"] == "cap_reached"

                # Without the scope, the key cannot add notes at all.
                reader = await person.post(
                    "/v1/sales-xray/integrations/keys",
                    headers=WRITE,
                    json={"name": "Reader", "scopes": ["leads:read"]},
                )
                no_scope = await app.post(
                    f"/v1/api/leads/{lead}/notes",
                    headers={"Authorization": f"Bearer {reader.json()['key']}"},
                    json={"note": "Hi", "request_id": "req-scope-001"},
                )
                assert no_scope.status_code == 403
                assert no_scope.json()["error"]["code"] == "scope_missing"
        finally:
            await setup.engine.dispose()

    run(exercise())
