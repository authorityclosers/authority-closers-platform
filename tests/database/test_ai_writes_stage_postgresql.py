"""Stage moves from apps on PostgreSQL (ai-writes.md, "stage"; API gap 3, 15 Nov 2026).

``POST /v1/api/leads/{id}/stage`` moves a lead through its pipeline's own stage list, behind
the same guardrails as the other AI writes: off until an owner turns "Stage moves" on (and
a switch saved by a page that doesn't show it yet keeps it), its own scope
(``leads:stage``), a reason always, Won, Lost and Junk waiting for a person
(``needs_review``), a retry changes nothing, the history says which app moved it, and Undo
puts the lead back where it was unless it moved again since. Fictional rows only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select

from ac_platform.http.routes import RouteContext
from ac_platform.integrations.api_http import install_integrations_api
from ac_platform.integrations.http import install_integrations_http
from ac_platform.integrations.models import IntegrationWrite
from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.journey import transitions
from ac_platform.lead_desk.models import Lead
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
DESK = "/v1/lead-desk"
CLOSED = ("won", "lost", "junk")
SWITCH = {"paused": False, "note": True, "task": True, "outcome": True, "update": False}


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


async def _places(setup: Any, lead_id: str) -> tuple[Any, Any, Any]:
    """Where the lead is, an open stage an app may move it to (asking at most a next
    action), and a closed one (which waits for a person)."""
    async with setup.sessions() as db:
        lead = await db.get(Lead, UUID(lead_id))
        assert lead is not None
        journey = await journeys.read(db, lead.tenant_id, journeys.pipeline_of(lead))
        current = journey.resolve(lead.stage, lead.step)
        allowed = transitions.moves(journey, current, can_manage=True)
        open_move = next(
            move
            for move in allowed
            if move.stage.kind not in CLOSED and set(move.needs) <= {transitions.NEXT_ACTION}
        )
        closed = next((move.stage for move in allowed if move.stage.kind in CLOSED), None) or next(
            stage for stage in journey.board() if stage.kind in CLOSED
        )
        return current, open_move, closed


async def _where(setup: Any, lead_id: str) -> tuple[str, str | None]:
    async with setup.sessions() as db:
        lead = await db.get(Lead, UUID(lead_id))
        assert lead is not None
        return lead.stage, lead.step


def test_an_app_moves_a_stage_only_when_allowed_and_undo_moves_it_back(
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
                        "name": "Fictional pipeline sync",
                        "scopes": ["leads:read", "leads:write", "leads:stage"],
                    },
                )
                assert made.status_code == 200, made.text
                bearer = {"Authorization": f"Bearer {made.json()['key']}"}
                added = await app.post(
                    "/v1/api/leads", headers=bearer, json={"name": "Ravi Deshmukh (test)"}
                )
                assert added.status_code == 201, added.text
                lead = added.json()["id"]
                current, move, closed = await _places(setup, lead)
                start = await _where(setup, lead)
                body: dict[str, Any] = {
                    "step": move.stage.key,
                    "reason": "Asked for the brochure on WhatsApp",
                    "request_id": "req-stage-0001",
                }
                if transitions.NEXT_ACTION in move.needs:
                    body["next_action_at"] = "2030-01-15T10:00:00+05:30"
                path = f"/v1/api/leads/{lead}/stage"

                # Off until an owner turns stage moves on.
                off = await app.post(path, headers=bearer, json=body)
                assert off.status_code == 403
                assert off.json()["error"]["code"] == "action_off"
                switch = (await person.get(f"{DESK}/ai-writes")).json()
                assert switch["stage"] is False
                on = await person.put(
                    f"{DESK}/ai-writes",
                    headers=WRITE,
                    json={"expected_revision": switch["revision"], **SWITCH, "stage": True},
                )
                assert on.status_code == 200, on.text
                # A page that doesn't show stage moves yet keeps them as saved.
                again = await person.put(
                    f"{DESK}/ai-writes",
                    headers=WRITE,
                    json={"expected_revision": on.json()["revision"], **SWITCH},
                )
                assert again.status_code == 200 and again.json()["stage"] is True

                for wrong, code in (
                    ({"reason": "   "}, "reason"),
                    ({"step": closed.key}, "needs_review"),
                    ({"step": "nowhere"}, "stage_unknown"),
                ):
                    refused = await app.post(
                        path,
                        headers=bearer,
                        json={**body, **wrong, "request_id": f"req-stage-{code}"},
                    )
                    assert refused.status_code == 422, (wrong, refused.text)
                    assert refused.json()["error"]["code"] == code
                preview = await app.post(
                    path,
                    headers=bearer,
                    json={**body, "request_id": "req-stage-0000", "preview": True},
                )
                assert preview.status_code == 200, preview.text
                assert preview.json()["would_move"]["to"] == move.stage.label
                assert await _where(setup, lead) == start

                first = await app.post(path, headers=bearer, json=body)
                assert first.status_code == 200, first.text
                assert first.json()["status"] == "applied"
                retried = await app.post(path, headers=bearer, json=body)
                assert retried.json()["replayed"] is True
                assert retried.json()["change_id"] == first.json()["change_id"]
                moved = await _where(setup, lead)
                assert moved[0] == move.stage.kind and moved != start
                same = await app.post(
                    path, headers=bearer, json={**body, "request_id": "req-stage-0002"}
                )
                assert same.status_code == 409 and same.json()["error"]["code"] == "no_change"

                # The history names the app; the ledger has field names, never the reason.
                detail = (await person.get(f"{DESK}/leads/{lead}")).json()
                line = [
                    event
                    for event in detail["events"]
                    if event.get("change_id") == first.json()["change_id"]
                ]
                assert line and line[0]["app_label"].startswith("API key")
                async with setup.sessions() as db:
                    ledger = await db.scalar(
                        select(IntegrationWrite).where(IntegrationWrite.action == "stage")
                    )
                    assert ledger is not None and "reason" in ledger.fields
                    assert "step" in ledger.fields

                # Undo puts the lead back where it was.
                undo = await app.post(
                    f"/v1/api/changes/{first.json()['change_id']}/undo", headers=bearer, json={}
                )
                assert undo.status_code == 200, undo.text
                assert undo.json()["status"] == "undone"
                assert await _where(setup, lead) == start

                # A later move wins over an undo of the one before it.
                second = await app.post(
                    path, headers=bearer, json={**body, "request_id": "req-stage-0003"}
                )
                assert second.status_code == 200, second.text
                _, onward, _ = await _places(setup, lead)
                later_body: dict[str, Any] = {
                    "step": onward.stage.key,
                    "reason": "Spoke again, moving on",
                    "request_id": "req-stage-0004",
                }
                if transitions.NEXT_ACTION in onward.needs:
                    later_body["next_action_at"] = "2030-01-16T10:00:00+05:30"
                later = await app.post(path, headers=bearer, json=later_body)
                assert later.status_code == 200, later.text
                late = await app.post(
                    f"/v1/api/changes/{second.json()['change_id']}/undo", headers=bearer, json={}
                )
                assert late.status_code == 409, late.text
                assert late.json()["error"]["code"] == "cannot_undo"
                assert "moved again" in late.json()["error"]["message"]
        finally:
            await setup.engine.dispose()

    run(exercise())
