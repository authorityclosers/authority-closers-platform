"""Bringing in old leads as history on PostgreSQL (owner, 2 Nov 2026). The Check step says each
of the file's stage words and the stage it reads as, how the dates read and the campaigns;
the import refuses until every word has a stage; then each old lead keeps its enquiry day,
campaign and stage, is given to nobody, credits nobody, and sits in no list but Old leads.
An ad or website enquiry from one of their numbers brings it back to Inbound, and All time
counts them by campaign. Made-up people only."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine, select

from ac_platform.lead_desk.enquiry_dates import IST
from ac_platform.lead_desk.models import Lead, LeadEvent
from ac_platform.lead_desk.store import LeadDesk, Viewer
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, world

SHEET = (
    b"Name,Phone,City,Enquiry Date,Status,Campaign\n"
    b"Asha Old Example,98760 76001,Poona,14/06/2026,Converted,Rooftop Old\n"
    b"Ravi Old Sample,98760 76002,Pune,25/07/2026,Not Answered,Rooftop Old\n"
    b"Meera Old Demo,98760 76003,Mumbai,02/08/2026,Warm,Expo List\n"
    b"Kiran Old Fresh,98760 76004,,not a date,Qualified,Expo List\n"
)
OLD = {"Asha Old Example", "Ravi Old Sample", "Meera Old Demo", "Kiran Old Fresh"}


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_old_leads_come_in_as_history_and_stay_out_of_work(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            here.as_admin()
            looked = await here.client.post(
                f"{BASE}/imports/preview",
                content=SHEET,
                headers={"Origin": ORIGIN, "Content-Type": "text/csv", "X-File-Name": "old.csv"},
            )
            assert looked.status_code == 200, looked.text
            seen = looked.json()
            assert seen["mapping"].get("stage") == "Status"
            # The enquiry date and campaign columns are found by their headers.
            assert seen["history_mapping"] == {"received": "Enquiry Date", "campaign": "Campaign"}
            mapping = {**seen["mapping"], **seen["history_mapping"]}

            def body(**more: Any) -> dict[str, Any]:
                return {
                    "command_id": str(uuid4()),
                    "file_name": "old.csv",
                    "mapping": mapping,
                    "rows": seen["rows"],
                    "side": "history",
                    **more,
                }

            # Only owners and admins bring in old leads.
            here.as_seller()
            refused = await here.client.post(
                f"{BASE}/imports/history-check", json=body(), headers=WRITE
            )
            assert refused.status_code == 403, refused.text

            here.as_admin()
            checked = await here.client.post(
                f"{BASE}/imports/history-check", json=body(), headers=WRITE
            )
            assert checked.status_code == 200, checked.text
            check = checked.json()
            words = {item["word"]: item["stage"] for item in check["stages"]}
            assert set(words) == {"Converted", "Not Answered", "Warm", "Qualified"}
            assert words["Warm"] is None and all(
                words[word] for word in ("Converted", "Not Answered", "Qualified")
            )
            assert (check["ready"], check["dates_read_as"], check["undated"]) == (False, "dmy", 1)
            assert {item["label"]: item["count"] for item in check["campaigns"]} == {
                "Rooftop Old": 2,
                "Expo List": 2,
            }

            # A word with no stage: nothing is written.
            stopped = await here.client.post(f"{BASE}/imports", json=body(), headers=WRITE)
            assert stopped.status_code == 422, stopped.text
            assert "Warm" in stopped.text
            assert await here.leads() == 0

            keen = words["Qualified"]
            done = await here.client.post(
                f"{BASE}/imports", json=body(stages={"Warm": keen}), headers=WRITE
            )
            assert done.status_code == 200, done.text
            result = done.json()
            assert (result["created"], result["side"], result["staged"]) == (4, "history", 4)
            assert (result["undated"], result["dates_read_as"]) == (1, "dmy")
            assert result["warnings"] == []

            async with here.setup.sessions() as db:
                leads = {
                    lead.name: lead
                    for lead in (
                        await db.scalars(select(Lead).where(Lead.tenant_id == here.tenant_id))
                    ).all()
                }
                assert set(leads) == OLD
                assert {lead.pipeline for lead in leads.values()} == {"history"}
                # Given to nobody; their own enquiry day; their campaign.
                assert {lead.owner_person_id for lead in leads.values()} == {None}
                asha = leads["Asha Old Example"]
                assert asha.received_at is not None
                assert asha.received_at.astimezone(IST).date().isoformat() == "2026-06-14"
                assert asha.source_label == "Rooftop Old"
                assert (asha.stage, leads["Meera Old Demo"].stage) == ("won", "interested")
                assert leads["Kiran Old Fresh"].received_at is None
                events = (
                    await db.scalars(
                        select(LeadEvent).where(
                            LeadEvent.lead_id.in_([lead.id for lead in leads.values()])
                        )
                    )
                ).all()
                # Nobody was given them, and no stage is anyone's move today.
                assert "assigned" not in {event.kind for event in events}
                assert {event.actor_person_id for event in events if event.kind == "stage"} == {
                    None
                }
                assert all(
                    event.data.get("history") is True
                    for event in events
                    if event.kind == "captured"
                )

            # In no list but Old leads.
            listed = await here.client.get(f"{BASE}/leads?scope=team&side=inbound")
            assert listed.status_code == 200, listed.text
            assert not OLD & {row["name"] for row in listed.json()["leads"]}
            cold = await here.client.get(f"{BASE}/leads?scope=team&side=cold")
            assert not OLD & {row["name"] for row in cold.json()["leads"]}
            old = await here.client.get(f"{BASE}/leads?scope=team&created=history")
            assert {row["name"] for row in old.json()["leads"]} == OLD

            # A website enquiry from an old lead's number: back on Inbound, stage kept.
            admin = here.setup.state.person_id
            async with here.setup.sessions() as db, db.begin():
                desk = LeadDesk(
                    db, Viewer(person_id=admin, tenant_id=here.tenant_id, role="admin", name="A")
                )
                lead, outcome = await desk.ingest(
                    {"name": "Asha Again", "phone": "98760 76001"}, source="webhook"
                )
                assert outcome == "repeat" and lead is not None
                assert (lead.pipeline, lead.stage) == ("live", "won")

            # Someone works an old lead: on Cold, in their lists. A note alone does not.
            async with here.setup.sessions() as db, db.begin():
                desk = LeadDesk(
                    db, Viewer(person_id=admin, tenant_id=here.tenant_id, role="admin", name="A")
                )
                ravi = await db.scalar(
                    select(Lead).where(
                        Lead.tenant_id == here.tenant_id, Lead.name == "Ravi Old Sample"
                    )
                )
                assert ravi is not None
                desk._event(ravi, "note", {"text": "Spoke last year"}, actor=admin)
                assert ravi.pipeline == "history"
                worked = desk._event(
                    ravi, "call", {"via": "phone", "direction": "outgoing"}, actor=admin
                )
                assert ravi.pipeline == "cold" and worked.data["from_history"] is True

            # All time counts the rest by campaign; a file of old leads reads Ended.
            report = await here.client.get(f"{BASE}/reports/pipeline?days=0")
            assert report.status_code == 200, report.text
            ever = report.json()
            assert ever["history_leads"] == 2
            rows = {row["label"]: row for row in ever["campaigns"]}
            assert (rows["Expo List"]["status"], rows["Expo List"]["history"]) == ("ended", True)
            assert rows["Expo List"]["interested"] == 2
            month = await here.client.get(f"{BASE}/reports/pipeline?days=30")
            assert month.json()["history_leads"] == 0

    run(exercise())
