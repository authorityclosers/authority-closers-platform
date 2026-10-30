"""The API lists leads by the organisation's own stages (orchestrator, 26 Oct 2026).

A new organisation on the recommended nine stages, with a second pipeline still on the
default list: every answer lists the stages, a stage key gives that stage's leads across
the pipelines (Interested no longer takes in Meeting Scheduled, which shares its kind),
pages go on with offset, open and the desk's old kinds still work, and anything
else is refused with the keys. Disposable loopback PostgreSQL, fictional rows only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
from sqlalchemy import update

from ac_platform.http.routes import RouteContext
from ac_platform.integrations.api_http import install_integrations_api
from ac_platform.integrations.http import install_integrations_http
from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.journey import pipelines
from ac_platform.lead_desk.journey.templates import TEMPLATES
from ac_platform.lead_desk.models import Lead
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
# The recommended nine, in the template's own order.
NINE = [
    stage.key for template in TEMPLATES if template.id == "recommended" for stage in template.stages
]


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_leads_follow_the_organisations_own_stages(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            context = RouteContext(setup.settings, setup.require_actor, setup.sessions)
            install_integrations_http(setup.app, context)
            install_integrations_api(setup.app, context)
            tenant, person = setup.state.tenant_id, setup.state.person_id
            now = datetime.now(UTC)
            async with setup.sessions() as db, db.begin():
                assert await journeys.start_organisation(db, tenant, person, now)
                # Once only: an organisation with a list keeps it.
                assert not await journeys.start_organisation(db, tenant, person, now)
                partners = await pipelines.create(
                    db, tenant, name="Partners", sources=[], by=person, now=now
                )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                made = await client.post(
                    "/v1/sales-xray/integrations/keys",
                    headers=WRITE,
                    json={"name": "Stages app", "scopes": ["leads:read", "leads:write"]},
                )
                assert made.status_code == 200, made.text
                bearer = {"Authorization": f"Bearer {made.json()['key']}"}
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as app:
                ids: dict[str, UUID] = {}
                for n, name in enumerate(("Asha", "Bina", "Chetan", "Dev", "Esha")):
                    added = await app.post(
                        "/v1/api/leads",
                        headers=bearer,
                        json={"name": f"{name} Fictional", "phone": f"+9198000000{n:02d}"},
                    )
                    assert added.status_code == 201, added.text
                    ids[name] = UUID(added.json()["id"])
                async with setup.sessions() as db, db.begin():
                    # Bina and Dev have a demo booked and Chetan is Interested: all three
                    # are the desk's kind "interested". Esha is in the second pipeline.
                    for name, step in (
                        ("Bina", "meeting_scheduled"),
                        ("Dev", "meeting_scheduled"),
                        ("Chetan", "interested"),
                    ):
                        await db.execute(
                            update(Lead)
                            .where(Lead.id == ids[name])
                            .values(stage="interested", step=step)
                        )
                    await db.execute(
                        update(Lead).where(Lead.id == ids["Esha"]).values(pipeline_key=partners.key)
                    )

                async def names(query: str) -> tuple[set[str], dict[str, Any]]:
                    answer = await app.get(f"/v1/api/leads{query}", headers=bearer)
                    assert answer.status_code == 200, answer.text
                    page = answer.json()
                    return {row["name"].split()[0] for row in page["leads"]}, page

                every, page = await names("")
                assert every == set(ids)
                keys = [item["key"] for item in page["stages"]]
                assert keys[:9] == NINE  # main's nine, then what Partners adds
                assert "follow_up" in keys[9:] and len(keys) == len(set(keys))
                labels = {item["key"]: item["label"] for item in page["stages"]}
                assert labels["meeting_scheduled"] == "Meeting Scheduled"

                booked, page = await names("?stage=meeting_scheduled")
                assert booked == {"Bina", "Dev"} and page["total"] == 2
                assert {row["step"] for row in page["leads"]} == {"meeting_scheduled"}
                assert {row["stage_label"] for row in page["leads"]} == {"Meeting Scheduled"}
                assert page["stages"][0]["key"] == "new"
                first, page = await names("?stage=meeting_scheduled&limit=1")
                assert len(first) == 1 and page["next_offset"] == 1
                rest, page = await names("?stage=meeting_scheduled&limit=1&offset=1")
                assert rest | first == {"Bina", "Dev"} and page["next_offset"] is None

                # Interested is its own stage now, not every lead of its kind.
                assert (await names("?stage=interested"))[0] == {"Chetan"}
                # A key both pipelines have takes each pipeline's own column.
                fresh, page = await names("?stage=new")
                assert fresh == {"Asha", "Esha"} and page["total"] == 2
                # open, every open lead, as before.
                assert (await names("?stage=open"))[0] == set(ids)

                refused = await app.get("/v1/api/leads?stage=hot", headers=bearer)
                assert refused.status_code == 422
                error = refused.json()["error"]
                assert error["code"] == "stage_unknown"
                assert error["message"].startswith(f"stage is one of open, {', '.join(NINE[:2])}")
                assert "meeting_scheduled" in error["message"]
        finally:
            await setup.engine.dispose()

    run(exercise())
