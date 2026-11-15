"""Assign and bulk changes from an organisation's key held by an owner or admin, on PostgreSQL
(ai-writes.md, "Amended 15 Nov"; API gap 3, 15 Nov 2026).

The admin's key gives a lead to a teammate and back (Undo), a seller's can't; it moves seven
leads at once only with the preview's ``preview_sha``, each lead its own change, and the
whole request is undone in one call; it gives every open lead (a stage filter) to a teammate;
and it closes a lead as Lost with the stage list's reason. Fictional rows only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select, update

from ac_platform.http.routes import RouteContext
from ac_platform.integrations.api_http import install_integrations_api
from ac_platform.integrations.http import install_integrations_http
from ac_platform.integrations.models import IntegrationWrite
from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.journey import transitions
from ac_platform.lead_desk.models import Lead
from ac_platform.tenancy.models import Membership
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _admin_sells, _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
DESK = "/v1/lead-desk"
CLOSED = ("won", "lost", "junk")
SWITCH = {"paused": False, "note": True, "task": True, "outcome": True, "update": False}


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


async def _role(setup: Any, role: str) -> None:
    async with setup.sessions() as db, db.begin():
        await db.execute(
            update(Membership)
            .where(
                Membership.tenant_id == setup.state.tenant_id,
                Membership.person_id == setup.state.person_id,
            )
            .values(role=role)
        )


async def _leads(setup: Any, ids: list[str]) -> dict[str, tuple[str, str | None]]:
    """Each lead's stage and owner."""
    async with setup.sessions() as db:
        rows = (
            await db.execute(
                select(Lead.id, Lead.stage, Lead.owner_person_id).where(
                    Lead.id.in_([UUID(item) for item in ids])
                )
            )
        ).all()
    return {str(lead): (stage, str(owner) if owner else None) for lead, stage, owner in rows}


def test_an_admins_key_assigns_and_changes_many_leads_with_preview_and_undo(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            await _admin_sells(setup)
            admin = str(setup.state.person_id)
            context = RouteContext(setup.settings, setup.require_actor, setup.sessions)
            install_integrations_http(setup.app, context)
            install_integrations_api(setup.app, context)
            transport = httpx.ASGITransport(app=setup.app)
            async with (
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as person,
                httpx.AsyncClient(transport=transport, base_url=ORIGIN) as app,
            ):
                person.cookies.set(setup.settings.session_cookie_name, setup.token)
                switch = (await person.get(f"{DESK}/ai-writes")).json()
                on = await person.put(
                    f"{DESK}/ai-writes",
                    headers=WRITE,
                    json={"expected_revision": switch["revision"], **SWITCH, "stage": True},
                )
                assert on.status_code == 200, on.text
                made = await person.post(
                    "/v1/sales-xray/integrations/keys",
                    headers=WRITE,
                    json={
                        "name": "Fictional pipeline admin",
                        "scopes": ["leads:read", "leads:write", "leads:stage", "leads:assign"],
                    },
                )
                assert made.status_code == 200, made.text
                bearer = {"Authorization": f"Bearer {made.json()['key']}"}
                ids = []
                for n in range(7):
                    added = await app.post(
                        "/v1/api/leads", headers=bearer, json={"name": f"Bulk Lead {n} (test)"}
                    )
                    assert added.status_code == 201, added.text
                    ids.append(added.json()["id"])
                start = await _leads(setup, ids)
                assert {owner for _, owner in start.values()} == {admin}
                # The teammate joins after: the lead rules gave every new lead to the admin.
                mate = str(
                    (
                        await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
                    ).person_id
                )

                # One lead to a teammate, and back.
                path = f"/v1/api/leads/{ids[0]}/assign"
                given = await app.post(
                    path, headers=bearer, json={"person_id": mate, "request_id": "req-assign-0001"}
                )
                assert given.status_code == 200, given.text
                assert given.json()["action"] == "assign"
                assert (await _leads(setup, ids[:1]))[ids[0]][1] == mate
                again = await app.post(
                    path, headers=bearer, json={"person_id": mate, "request_id": "req-assign-0001"}
                )
                assert again.json()["replayed"] is True
                back = await app.post(
                    f"/v1/api/changes/{given.json()['change_id']}/undo", headers=bearer, json={}
                )
                assert back.status_code == 200, back.text
                assert (await _leads(setup, ids[:1]))[ids[0]][1] == admin
                # A seller's key can't give leads away.
                await _role(setup, "member")
                seller = await app.post(
                    path, headers=bearer, json={"person_id": mate, "request_id": "req-assign-0002"}
                )
                assert seller.status_code == 403
                assert seller.json()["error"]["code"] == "managers_only"
                many = await app.post(
                    "/v1/api/leads/bulk",
                    headers=bearer,
                    json={
                        "lead_ids": ids,
                        "change": {"assign": {"person_id": mate}},
                        "request_id": "req-bulk-0000",
                        "preview": True,
                    },
                )
                assert many.status_code == 403
                await _role(setup, "admin")

                # Seven at once: preview, then exactly what the preview showed.
                async with setup.sessions() as db:
                    lead = await db.get(Lead, UUID(ids[0]))
                    assert lead is not None
                    journey = await journeys.read(db, lead.tenant_id, journeys.pipeline_of(lead))
                current = journey.resolve(lead.stage, lead.step)
                move = next(
                    item
                    for item in transitions.moves(journey, current, can_manage=True)
                    if item.stage.kind not in CLOSED
                    and set(item.needs) <= {transitions.NEXT_ACTION}
                )
                stage: dict[str, Any] = {"step": move.stage.key, "reason": "Batch follow-up"}
                if transitions.NEXT_ACTION in move.needs:
                    stage["next_action_at"] = "2030-02-01T10:00:00+05:30"
                body = {"lead_ids": ids, "change": {"stage": stage}, "request_id": "req-bulk-0001"}
                shown = await app.post(
                    "/v1/api/leads/bulk", headers=bearer, json={**body, "preview": True}
                )
                assert shown.status_code == 200, shown.text
                assert shown.json()["leads"] == 7 and len(shown.json()["preview_sha"]) == 64
                assert await _leads(setup, ids) == start
                blind = await app.post("/v1/api/leads/bulk", headers=bearer, json=body)
                assert blind.status_code == 409
                assert blind.json()["error"]["code"] == "preview_first"
                sha = shown.json()["preview_sha"]
                done = await app.post(
                    "/v1/api/leads/bulk", headers=bearer, json={**body, "preview_sha": sha}
                )
                assert done.status_code == 200, done.text
                assert done.json()["applied"] == 7 and done.json()["failed_count"] == 0
                moved = await _leads(setup, ids)
                assert {stage_kind for stage_kind, _ in moved.values()} == {move.stage.kind}
                retried = await app.post(
                    "/v1/api/leads/bulk", headers=bearer, json={**body, "preview_sha": sha}
                )
                assert retried.status_code == 200, retried.text
                async with setup.sessions() as db:
                    rows = int(
                        await db.scalar(
                            select(func.count())
                            .select_from(IntegrationWrite)
                            .where(IntegrationWrite.action == "stage")
                        )
                        or 0
                    )
                assert rows == 7  # each lead's change once, however often it was sent
                # The same key moves one of the seven again, in another request: undoing the
                # bulk request still finds all seven of its own changes (Codex P2, PR 619),
                # and keeps the one moved since, saying so.
                onward = next(
                    item
                    for item in transitions.moves(journey, move.stage, can_manage=True)
                    if item.stage.kind not in CLOSED
                    and item.stage.key not in (move.stage.key, current.key)
                    and set(item.needs) <= {transitions.NEXT_ACTION}
                )
                again: dict[str, Any] = {
                    "step": onward.stage.key,
                    "reason": "Spoke again, moving on",
                    "request_id": "req-single-0001",
                }
                if transitions.NEXT_ACTION in onward.needs:
                    again["next_action_at"] = "2030-02-02T10:00:00+05:30"
                moved_on = await app.post(
                    f"/v1/api/leads/{ids[0]}/stage", headers=bearer, json=again
                )
                assert moved_on.status_code == 200, moved_on.text
                undone = await app.post(
                    "/v1/api/changes/undo-request",
                    headers=bearer,
                    json={"request_id": "req-bulk-0001"},
                )
                assert undone.status_code == 200, undone.text
                assert undone.json()["changes"] == 7 and undone.json()["undone"] == 6
                assert [item["lead_id"] for item in undone.json()["kept"]] == [ids[0]]
                after = await _leads(setup, ids)
                assert {lead: after[lead] for lead in ids[1:]} == {
                    lead: start[lead] for lead in ids[1:]
                }
                assert after[ids[0]][0] == onward.stage.kind

                # Every open lead (a stage filter) to the teammate.
                assign = {
                    "filter": {"stage": "open"},
                    "change": {"assign": {"person_id": mate}},
                    "request_id": "req-bulk-0002",
                }
                shown = await app.post(
                    "/v1/api/leads/bulk", headers=bearer, json={**assign, "preview": True}
                )
                assert shown.status_code == 200 and shown.json()["leads"] == 7, shown.text
                given_all = await app.post(
                    "/v1/api/leads/bulk",
                    headers=bearer,
                    json={**assign, "preview_sha": shown.json()["preview_sha"]},
                )
                assert given_all.json()["applied"] == 7, given_all.text
                assert {owner for _, owner in (await _leads(setup, ids)).values()} == {mate}

                # An admin's key closes a lead with the stage list's reason.
                lost = next(item for item in journey.board() if item.kind == "lost")
                code = next(key for key, _ in transitions.reasons_of(lost) if key != "other")
                closed = await app.post(
                    f"/v1/api/leads/{ids[1]}/stage",
                    headers=bearer,
                    json={
                        "step": lost.key,
                        "reason": "Bought from someone else",
                        "reason_code": code,
                        "request_id": "req-close-0001",
                    },
                )
                assert closed.status_code == 200, closed.text
                assert (await _leads(setup, ids[1:2]))[ids[1]][0] == "lost"
        finally:
            await setup.engine.dispose()

    run(exercise())
