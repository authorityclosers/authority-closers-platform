"""A CRM's export through the import on PostgreSQL (universal intake, docs/product/lead-desk/
universal-intake.md, slice 1): a Zoho CRM file is recognised and every column matched with
none picked by hand; an empty Phone gives way to Mobile and a cell with two numbers gives
the first; first and last names are joined; the CRM's status words land in the pipeline's
stages and owners match by email; a row with no phone and a known email is a repeat; the
leads say which CRM's export they came from; the same file again adds nothing. Made-up
people only."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine, select

from ac_platform.identity.models import Person
from ac_platform.lead_desk.models import Lead
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_a_zoho_export_imports_in_one_click(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            async with here.setup.sessions() as db:
                email = await db.scalar(
                    select(Person.email).where(Person.id == here.seller.person_id)
                )
            assert email
            here.as_admin()
            # Already a lead, known by email only.
            known = await here.client.post(
                f"{BASE}/leads",
                json={
                    "command_id": str(uuid4()),
                    "name": "Neha Demo",
                    "email": "neha.demo@example.com",
                },
                headers=WRITE,
            )
            assert known.status_code == 201, known.text
            sheet = (
                "Record Id,Lead Owner,First Name,Last Name,Company,Email,Phone,Mobile,"
                "Lead Status,City,Created Time\n"
                f"zcrm_1,{email},Asha,Example,Example Solar,asha@example.com,,98760 72001,"
                "Attempted to Contact,Pune,2026-10-01 10:00:00\n"
                f'zcrm_2,{email.upper()},Ravi,Sample,,ravi@example.com,"98760 72002, 98760 72099",,'
                "Qualified,Nashik,2026-10-02 11:00:00\n"
                "zcrm_3,Nobody Known,Neha,Demo,,NEHA.DEMO@example.com,,,Closed Won,Nagpur,"
                "2026-10-03 12:00:00\n"
            ).encode()
            looked = await here.client.post(
                f"{BASE}/imports/preview",
                content=sheet,
                headers={"Origin": ORIGIN, "Content-Type": "text/csv", "X-File-Name": "zoho.csv"},
            )
            assert looked.status_code == 200, looked.text
            seen = looked.json()
            assert seen["detected"] == "Zoho CRM"
            assert seen["importable"] == 3 and seen["with_phone"] == 2
            assert seen["known_leads"] == 1
            assert seen["mapping"]["stage"] == "Lead Status"
            assert seen["mapping"]["owner"] == "Lead Owner"

            body = {
                "command_id": str(uuid4()),
                "file_name": "zoho.csv",
                "mapping": seen["mapping"],
                "rows": seen["rows"],
                "source_name": seen["detected"],
            }
            done = await here.client.post(f"{BASE}/imports", json=body, headers=WRITE)
            assert done.status_code == 200, done.text
            result = done.json()
            assert (result["created"], result["repeats"]) == (2, 1)
            assert (result["staged"], result["owned"]) == (2, 2)

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
                emailed = (
                    await db.scalars(
                        select(Lead).where(
                            Lead.tenant_id == here.tenant_id,
                            Lead.email == "neha.demo@example.com",
                        )
                    )
                ).all()
            asha = leads["+919876072001"]
            assert asha.name == "Asha Example" and asha.company == "Example Solar"
            assert asha.source_label == "Zoho CRM export: zoho.csv"
            assert asha.stage == "not_connected"
            assert asha.owner_person_id == here.seller.person_id
            ravi = leads["+919876072002"]
            assert ravi.name == "Ravi Sample" and ravi.stage == "interested"
            assert ravi.owner_person_id == here.seller.person_id
            assert "+919876072099" not in leads
            # The phone-less row with a known email is that lead again, not a second one.
            assert len(emailed) == 1 and emailed[0].repeats == 1

            # The same file again adds nothing.
            again = await here.client.post(
                f"{BASE}/imports", json={**body, "command_id": str(uuid4())}, headers=WRITE
            )
            assert again.json()["created"] == 0

    run(exercise())
