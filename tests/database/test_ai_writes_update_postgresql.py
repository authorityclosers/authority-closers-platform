"""Lead updates from apps on PostgreSQL (ai-writes.md, "update"; first used by Pulse).

``PATCH /v1/api/leads/{id}`` changes a lead's name, company, city, interest or language
behind the same guardrails as notes and tasks: off until an owner turns "Lead details"
on, its own scope (``leads:update``), only the allowed fields (phone and email wait for
review), a retry changes nothing, the history says which app changed it, and Undo puts
back what was there unless a person changed those fields since. Fictional rows only.
"""

from __future__ import annotations

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
from ac_platform.lead_desk.models import Lead
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
DESK = "/v1/lead-desk"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_an_app_changes_lead_details_only_when_allowed_and_undo_restores_them(
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
                        "name": "Fictional sync",
                        "scopes": ["leads:read", "leads:write", "leads:update"],
                    },
                )
                assert made.status_code == 200, made.text
                bearer = {"Authorization": f"Bearer {made.json()['key']}"}
                added = await app.post(
                    "/v1/api/leads",
                    headers=bearer,
                    json={"name": "Asha Kulkarni (test)", "company": "Old Co", "city": "Pune"},
                )
                assert added.status_code == 201, added.text
                lead = added.json()["id"]
                change = {
                    "fields": {"company": "Greenleaf Cafe", "city": "Mumbai"},
                    "request_id": "req-update-0001",
                }

                # Off until an owner turns "Lead details" on.
                off = await app.patch(f"/v1/api/leads/{lead}", headers=bearer, json=change)
                assert off.status_code == 403
                assert off.json()["error"]["code"] == "action_off"
                switch = (await person.get(f"{DESK}/ai-writes")).json()
                assert switch["update"] is False
                on = await person.put(
                    f"{DESK}/ai-writes",
                    headers=WRITE,
                    json={
                        "expected_revision": switch["revision"],
                        "paused": False,
                        "note": True,
                        "task": True,
                        "outcome": True,
                        "update": True,
                    },
                )
                assert on.status_code == 200, on.text

                first = await app.patch(f"/v1/api/leads/{lead}", headers=bearer, json=change)
                assert first.status_code == 200, first.text
                assert first.json()["status"] == "applied"
                again = await app.patch(f"/v1/api/leads/{lead}", headers=bearer, json=change)
                assert again.json()["replayed"] is True
                assert again.json()["change_id"] == first.json()["change_id"]
                async with setup.sessions() as db:
                    row = await db.get(Lead, UUID(lead))
                    assert row is not None and (row.company, row.city) == (
                        "Greenleaf Cafe",
                        "Mumbai",
                    )

                for fields, code in (
                    ({"phone": "+919000000101"}, "needs_review"),
                    ({"email": "asha@example.test"}, "needs_review"),
                    ({"stage": "won"}, "field_not_allowed"),
                    ({"name": ""}, "field_value"),
                ):
                    refused = await app.patch(
                        f"/v1/api/leads/{lead}",
                        headers=bearer,
                        json={"fields": fields, "request_id": f"req-{code}-{len(fields)}x"},
                    )
                    assert refused.status_code == 422, fields
                    assert refused.json()["error"]["code"] == code
                preview = await app.patch(
                    f"/v1/api/leads/{lead}",
                    headers=bearer,
                    json={
                        "fields": {"city": "Nagpur"},
                        "request_id": "req-update-0002",
                        "preview": True,
                    },
                )
                assert preview.json()["would_change"] == {"city": "Nagpur"}

                # The history names the app; the ledger has field names, never values.
                detail = (await person.get(f"{DESK}/leads/{lead}")).json()
                edited = [
                    event
                    for event in detail["events"]
                    if event.get("change_id") == first.json()["change_id"]
                ]
                assert edited and edited[0]["app_label"].startswith("API key")
                async with setup.sessions() as db:
                    ledger = await db.scalar(
                        select(IntegrationWrite).where(IntegrationWrite.action == "update")
                    )
                    assert ledger is not None and ledger.fields == ["city", "company"]

                # Undo puts back what was there.
                undo = await app.post(
                    f"/v1/api/changes/{first.json()['change_id']}/undo", headers=bearer, json={}
                )
                assert undo.status_code == 200, undo.text
                async with setup.sessions() as db:
                    row = await db.get(Lead, UUID(lead))
                    assert row is not None and (row.company, row.city) == ("Old Co", "Pune")

                # A person's later change wins over an undo.
                second = await app.patch(
                    f"/v1/api/leads/{lead}",
                    headers=bearer,
                    json={"fields": {"city": "Thane"}, "request_id": "req-update-0003"},
                )
                assert second.status_code == 200, second.text
                current = (await person.get(f"{DESK}/leads/{lead}")).json()
                edited_by_person = await person.patch(
                    f"{DESK}/leads/{lead}",
                    headers=WRITE,
                    json={
                        "command_id": str(uuid4()),
                        "expected_revision": current["lead"]["revision"],
                        "city": "Navi Mumbai",
                    },
                )
                assert edited_by_person.status_code == 200, edited_by_person.text
                late = await app.post(
                    f"/v1/api/changes/{second.json()['change_id']}/undo", headers=bearer, json={}
                )
                assert late.status_code == 409
                assert late.json()["error"]["code"] == "changed_since"
        finally:
            await setup.engine.dispose()

    run(exercise())
