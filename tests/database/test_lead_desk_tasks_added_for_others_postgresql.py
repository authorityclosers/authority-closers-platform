"""A task added on someone else's lead shows on the list of the person who added it, on
PostgreSQL (owner bugs 218-219, 15 Nov 2026: the owner added WhatsApp tasks on his sellers'
leads and found them neither on Home's My tasks nor on Tasks, because a task on a lead goes on
the lead owner's list).

The admin adds a task on a teammate's lead: it stays the teammate's to do (on their list), and
it now also shows on the admin's own list (``GET /v1/lead-desk/tasks``, which Home and Tasks
read), with the counts.
Fictional rows only.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import update

from ac_platform.http.routes import RouteContext
from ac_platform.identity.models import Person
from ac_platform.integrations.api_http import install_integrations_api
from ac_platform.integrations.http import install_integrations_http
from ac_platform.lead_desk.models import Lead, LeadTask
from ac_platform.lead_desk.store import person_name
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _admin_sells, _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
DESK = "/v1/lead-desk"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_a_task_added_on_a_teammates_lead_shows_on_the_adders_list_too(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)  # the signed-in person is an admin
            await _admin_sells(setup)
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
                    json={"name": "Fictional setup", "scopes": ["leads:read", "leads:write"]},
                )
                assert made.status_code == 200, made.text
                bearer = {"Authorization": f"Bearer {made.json()['key']}"}
                leads = []
                for name in ("Kiran Patil (test)", "Neha Rao (test)"):
                    added = await app.post("/v1/api/leads", headers=bearer, json={"name": name})
                    assert added.status_code == 201, added.text
                    leads.append(UUID(added.json()["id"]))
                mate = (
                    await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
                ).person_id
                # Both leads are the teammate's.
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(Lead).where(Lead.id.in_(leads)).values(owner_person_id=mate)
                    )

                due = (datetime.now(UTC) + timedelta(days=3)).replace(microsecond=0)
                tasks = []
                for lead in leads:
                    added_task = await person.post(
                        f"{DESK}/leads/{lead}/tasks",
                        headers=WRITE,
                        json={
                            "command_id": str(uuid4()),
                            "kind": "whatsapp",
                            "starts_at": due.isoformat(),
                        },
                    )
                    assert added_task.status_code == 200, added_task.text
                    tasks.append(added_task.json()["task_id"])
                async with setup.sessions() as db:
                    on_lead = await db.get(LeadTask, UUID(tasks[0]))
                    assert on_lead is not None
                    assert on_lead.owner_person_id == mate  # still the teammate's to do

                mine = await person.get(f"{DESK}/tasks", params={"view": "upcoming"})
                assert mine.status_code == 200, mine.text
                shown = {item["task_id"] for item in mine.json()["tasks"]}
                assert set(tasks) <= shown
                assert mine.json()["counts"]["upcoming"] >= 2
                # Each says whose it is, for "for <name>" on the row.
                async with setup.sessions() as db:
                    mate_name = person_name(await db.get(Person, mate))
                listed = {item["task_id"]: item for item in mine.json()["tasks"]}
                assert {listed[task]["owner_name"] for task in tasks} == {mate_name}
                theirs = await person.get(
                    f"{DESK}/tasks", params={"view": "upcoming", "person": str(mate)}
                )
                assert set(tasks) <= {item["task_id"] for item in theirs.json()["tasks"]}
        finally:
            await setup.engine.dispose()

    run(exercise())
