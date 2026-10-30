"""The stage editor through the Sales Xray CRM's HTTP API on PostgreSQL
(stages-views-sources.md §3, owner + Dipak, 30 Oct 2026).

A manager uses the recommended nine stages, hides one from sellers, gives one a colour,
renames the first stage's Cold Leads name and removes a stage that holds a lead, picking
where the lead goes: the lead moves with one history line, and the stage stays in history.
"""

from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, update

from ac_platform.lead_desk.models import Lead, LeadEvent
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_journey_postgresql import BASE, WRITE, _organisation


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_the_stage_editor_saves_its_settings_and_moves_a_removed_stages_leads(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                used = await client.post(
                    f"{BASE}/journey/template",
                    json={"expectedVersion": 0, "template": "recommended"},
                    headers=WRITE,
                )
                assert used.status_code == 200, used.text
                view = used.json()
                assert [stage["label"] for stage in view["stages"]] == [
                    "New Lead",
                    "Open Leads",
                    "Not Connected",
                    "Interested",
                    "Meeting Scheduled",
                    "Meeting Done",
                    "Won",
                    "Closed / Lost",
                    "Junk Lead",
                ]
                first = view["stages"][0]
                assert (first["coldLabel"], first["visible"], first["color"]) == (
                    "Unworked",
                    True,
                    None,
                )

                added = await client.post(
                    f"{BASE}/leads",
                    json={
                        "command_id": str(uuid4()),
                        "name": "Fictional Buyer",
                        "phone": "98765 43210",
                    },
                    headers=WRITE,
                )
                assert added.status_code == 201, added.text
                lead = added.json()["lead"]
                # The lead had its meeting (set here directly: the list's moves take a
                # new lead there in steps, each asking its own questions).
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(Lead)
                        .where(Lead.id == UUID(lead["lead_id"]))
                        .values(stage="interested", step="meeting_done")
                    )

                stages: list[dict[str, Any]] = [
                    {"key": stage["key"], "label": stage["label"]}
                    for stage in view["stages"]
                    if stage["key"] != "meeting_done"
                ]
                stages[0]["coldLabel"] = "Fresh list"
                stages[1]["visible"] = False
                stages[3]["color"] = "amber"
                version = view["version"]

                # The first stage is always shown to sellers; a colour is one of the dots;
                # an open stage's leads can't be put in Won. Nothing is saved.
                for wrong_first, places in (
                    ({"visible": False}, {}),
                    ({"color": "#ff0000"}, {}),
                    ({}, {"meeting_done": "won"}),
                ):
                    refused = await client.put(
                        f"{BASE}/journey",
                        json={
                            "expectedVersion": version,
                            "stages": [{**stages[0], **wrong_first}, *stages[1:]],
                            "map": places,
                        },
                        headers=WRITE,
                    )
                    assert refused.status_code == 422, refused.text
                assert (await client.get(f"{BASE}/journey")).json()["version"] == version

                saved = await client.put(
                    f"{BASE}/journey",
                    json={
                        "expectedVersion": version,
                        "stages": stages,
                        "map": {"meeting_done": "interested"},
                    },
                    headers=WRITE,
                )
                assert saved.status_code == 200, saved.text
                by_key = {stage["key"]: stage for stage in saved.json()["stages"]}
                assert by_key["new"]["coldLabel"] == "Fresh list"
                assert by_key["open_leads"]["visible"] is False
                assert by_key["interested"]["color"] == "amber"
                assert by_key["meeting_done"]["archived"] is True
                assert (by_key["interested"]["leads"], by_key["meeting_done"]["leads"]) == (1, 0)

            async with setup.sessions() as db:
                stored = await db.scalar(select(Lead).where(Lead.id == UUID(lead["lead_id"])))
                assert stored is not None
                assert (stored.stage, stored.step) == ("interested", "interested")
                moves = (
                    await db.scalars(
                        select(LeadEvent)
                        .where(LeadEvent.lead_id == stored.id, LeadEvent.kind == "stage")
                        .order_by(LeadEvent.created_at)
                    )
                ).all()
                assert len(moves) == 1
                last = moves[-1].data
                assert (last["source"], last["from_label"], last["to_label"]) == (
                    "template",
                    "Meeting Done",
                    "Interested",
                )
        finally:
            await setup.engine.dispose()

    run(exercise())
