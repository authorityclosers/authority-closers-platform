"""The duplicate queue through the Sales X-Ray API (docs/product/lead-desk/duplicates.md, D4b):
an organisation's key with leads:read reads the queue and one pair; another organisation's
pair answers 404; a key without leads:read is refused. Read only: nothing merges from here.
Made-up people only."""

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
from ac_platform.lead_desk import duplicate_scan
from ac_platform.lead_desk.models import LeadDuplicatePair
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_integrations_postgresql import PAGE, WRITE
from tests.database.test_lead_desk_duplicate_scan_postgresql import NOW, lead
from tests.database.test_lead_desk_postgresql import _organisation


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_an_organisation_key_reads_the_duplicate_queue(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            mine = UUID(str(setup.state.tenant_id))
            other = (await seed(setup.engine)).tenant_id
            async with setup.sessions() as db, db.begin():
                db.add_all(
                    [
                        lead(mine, "Asha Example", "+919876079001", "asha@gamil.com"),
                        lead(mine, "Asha Example", "+19876079001", "asha@gmail.com"),
                        lead(other, "Asha Example", "+919876079001", "asha@gamil.com"),
                        lead(other, "Asha Example", "+19876079001", "asha@gmail.com"),
                    ]
                )
            for tenant in (mine, other):
                async with setup.sessions() as db, db.begin():
                    await duplicate_scan.scan(db, tenant, NOW)
            async with setup.sessions() as db:
                pairs = {
                    row.tenant_id: row.id
                    for row in (await db.scalars(select(LeadDuplicatePair))).all()
                }
            context = RouteContext(setup.settings, setup.require_actor, setup.sessions)
            install_integrations_http(setup.app, context)
            install_integrations_api(setup.app, context)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                keys = {}
                for name, scopes in (("Leads", ["leads:read"]), ("Calls", ["calls:read"])):
                    made = await client.post(
                        f"{PAGE}/keys", headers=WRITE, json={"name": name, "scopes": scopes}
                    )
                    assert made.status_code == 200, made.text
                    keys[name] = {"Authorization": f"Bearer {made.json()['key']}"}
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as app:
                queue = await app.get("/v1/api/duplicates", headers=keys["Leads"])
                assert queue.status_code == 200, queue.text
                body = queue.json()
                assert body["total"] == 1 and body["counts"] == {"probable": 1}
                assert body["pairs"][0]["pair_id"] == str(pairs[mine])
                one = await app.get(f"/v1/api/duplicates/{pairs[mine]}", headers=keys["Leads"])
                assert one.status_code == 200, one.text
                assert "same email apart from a typo" in one.json()["pair"]["reasons"]
                theirs = await app.get(f"/v1/api/duplicates/{pairs[other]}", headers=keys["Leads"])
                assert theirs.status_code == 404
                refused = await app.get("/v1/api/duplicates", headers=keys["Calls"])
                assert refused.status_code == 403
                assert refused.json()["error"]["code"] == "scope_missing"
                assert (
                    await app.post("/v1/api/duplicates", headers=keys["Leads"], json={})
                ).status_code == 405
        finally:
            await setup.engine.dispose()

    run(exercise())
