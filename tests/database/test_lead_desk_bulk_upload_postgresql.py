"""Bulk upload on PostgreSQL (stages-views-sources.md section 5, owner + Dipak, 30 Oct 2026):
an owner uploads a cold list, gives two of its new leads to a seller and leaves the rest
unassigned, starting them in Open Leads; a number already a lead keeps its own side, owner
and stage; a stage past Interested, or someone off the team, is refused before anything is
added. Made-up people only."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine, select, update

from ac_platform.lead_desk.models import Lead
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_a_cold_list_goes_to_the_picked_seller_and_starts_where_the_owner_chose(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            here.as_admin()
            journey = (await here.client.get(f"{BASE}/journey")).json()
            used = await here.client.post(
                f"{BASE}/journey/template",
                json={"expectedVersion": journey["version"], "template": "recommended"},
                headers=WRITE,
            )
            assert used.status_code == 200, used.text
            known = await here.client.post(
                f"{BASE}/leads",
                json={"command_id": str(uuid4()), "name": "Kiran Sample", "phone": "98760 73009"},
                headers=WRITE,
            )
            assert known.status_code == 201, known.text
            before = await here.leads()

            sheet = (
                b"Name,Phone\n"
                b"Asha Example,98760 73001\n"
                b"Ravi Sample,98760 73002\n"
                b"Meera Demo,98760 73003\n"
                b"Kiran Sample,98760 73009\n"
            )
            looked = await here.client.post(
                f"{BASE}/imports/preview",
                content=sheet,
                headers={"Origin": ORIGIN, "Content-Type": "text/csv", "X-File-Name": "cold.csv"},
            )
            assert looked.status_code == 200, looked.text
            seen = looked.json()
            assert seen["known_leads"] == 1
            body = {
                "command_id": str(uuid4()),
                "file_name": "cold.csv",
                "mapping": seen["mapping"],
                "rows": seen["rows"],
                "side": "cold",
                "assign": "people",
                "shares": [{"person_id": str(here.seller.person_id), "count": 2}],
                "step": "open_leads",
            }

            # A stage past Interested, or someone off the team: refused, nothing added.
            for wrong in ({"step": "won"}, {"shares": [{"person_id": str(uuid4()), "count": 1}]}):
                refused = await here.client.post(
                    f"{BASE}/imports",
                    json={**body, **wrong, "command_id": str(uuid4())},
                    headers=WRITE,
                )
                assert refused.status_code == 422, refused.text
            assert await here.leads() == before

            done = await here.client.post(f"{BASE}/imports", json=body, headers=WRITE)
            assert done.status_code == 200, done.text
            result = done.json()
            assert (result["created"], result["repeats"], result["side"]) == (3, 1, "cold")
            assert [(item["person_id"], item["leads"]) for item in result["given"]] == [
                (str(here.seller.person_id), 2)
            ]
            assert (result["assigned"], result["waiting"]) == (2, 1)

            async with here.setup.sessions() as db:
                leads = {
                    lead.phone: lead
                    for lead in (
                        await db.scalars(
                            select(Lead).where(
                                Lead.tenant_id == here.tenant_id, Lead.phone.is_not(None)
                            )
                        )
                    ).all()
                }
            new = [leads[phone] for phone in ("+919876073001", "+919876073002", "+919876073003")]
            assert [lead.pipeline for lead in new] == ["cold"] * 3
            assert [lead.owner_person_id for lead in new] == [
                here.seller.person_id,
                here.seller.person_id,
                None,
            ]
            assert [(lead.stage, lead.step) for lead in new] == [("follow_up", "open_leads")] * 3
            # Already a lead: it keeps its side, its stage and its owner.
            kiran = leads["+919876073009"]
            assert (kiran.pipeline, kiran.stage, kiran.repeats) == ("live", "new", 1)

            # A lead typed in says Inbound or Cold too.
            typed = await here.client.post(
                f"{BASE}/leads",
                json={
                    "command_id": str(uuid4()),
                    "name": "Nisha Example",
                    "phone": "98760 73010",
                    "side": "cold",
                },
                headers=WRITE,
            )
            assert typed.status_code == 201, typed.text
            async with here.setup.sessions() as db:
                nisha = await db.scalar(
                    select(Lead).where(
                        Lead.tenant_id == here.tenant_id, Lead.phone == "+919876073010"
                    )
                )
            assert nisha is not None and nisha.pipeline == "cold"

            # A cold list given to a seller is worked over days: the reassign sweep leaves it.
            team = (await here.client.get(f"{BASE}/team")).json()
            saved = await here.client.put(
                f"{BASE}/settings",
                json={
                    "expected_revision": team["settings"]["revision"],
                    "auto_reassign": True,
                    "reassign_minutes": 15,
                },
                headers=WRITE,
            )
            assert saved.status_code == 200, saved.text
            # Only leads with a seller have an assignment time; the one still waiting has none.
            async with here.setup.sessions() as db, db.begin():
                await db.execute(
                    update(Lead)
                    .where(
                        Lead.tenant_id == here.tenant_id,
                        Lead.pipeline == "cold",
                        Lead.owner_person_id.is_not(None),
                    )
                    .values(assigned_at=datetime.now(UTC) - timedelta(days=1))
                )
            swept = await here.client.post(f"{BASE}/sweep", headers=WRITE)
            assert swept.status_code == 200, swept.text
            assert swept.json()["moved"] == 0

    run(exercise())
