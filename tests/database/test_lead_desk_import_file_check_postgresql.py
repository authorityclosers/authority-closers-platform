"""The import's Check on PostgreSQL (owner's import study, 16 Nov 2026). Before anything is
written, the file says what each stage word becomes and where a word that is no stage here
starts, whose each owner name is and how many new leads keep it, and what becomes of every
column. Then the import gives rows that name a teammate to that teammate, shares only the
rest, starts a word that is no stage in the stage picked, and keeps the word on the lead.
Made-up people only."""

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


def sheet(admin: str) -> bytes:
    return (
        "Sr No,Customer Name,Mobile No.,City/Town,Status,Assigned To,Remarks,lead_id,Blank\n"
        f"1,Rahul Kumar Example,98760 74001,Pune,Call back,{admin},kal call karna,x1,\n"
        "2,Pooja Sharma Sample,98760 74002,Nashik,Will think,,thoda time chahiye,x2,\n"
        "3,Amit Verma Demo,98760 74003,Thane,Call back,Nobody Known,,x3,\n"
        f"4,Sneha Patil Fresh,98760 74004,Pune,New,{admin},,x4,\n"
        f"5,Rahul Kumar Example,98760 74001,Pune,Call back,{admin},repeat row,x5,\n"
    ).encode()


def test_the_check_accounts_for_owners_stages_and_every_column(
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
            admin_id = str(here.setup.state.person_id)
            seller_id = str(here.seller.person_id)
            # The made-up admin and seller share a name, so the file names the admin by
            # email (people_index: a name two people have matches neither).
            async with here.setup.sessions() as db:
                admin = await db.scalar(
                    select(Person.email).where(Person.id == here.setup.state.person_id)
                )
            assert admin

            looked = await here.client.post(
                f"{BASE}/imports/preview",
                content=sheet(admin),
                headers={"Origin": ORIGIN, "Content-Type": "text/csv", "X-File-Name": "ns.csv"},
            )
            assert looked.status_code == 200, looked.text
            seen = looked.json()
            # City/Town is the City (it went unmatched before).
            assert seen["mapping"]["city"] == "City/Town"
            assert (seen["mapping"]["stage"], seen["mapping"]["owner"]) == (
                "Status",
                "Assigned To",
            )

            def body(**more: Any) -> dict[str, Any]:
                return {
                    "command_id": str(uuid4()),
                    "file_name": "ns.csv",
                    "mapping": seen["mapping"],
                    "rows": seen["rows"],
                    "headers": seen["headers"],
                    "side": "cold",
                    "step": "open_leads",
                    **more,
                }

            checked = await here.client.post(f"{BASE}/imports/check", json=body(), headers=WRITE)
            assert checked.status_code == 200, checked.text
            check = checked.json()
            stages = {item["word"]: (item["stage"], item["rows"]) for item in check["stages"]}
            assert stages["Call back"] == ("open_leads", 3)
            assert stages["Will think"] == (None, 1)
            # A word that is no stage starts where the owner picked.
            assert check["unmatched_stage"] == "Open Leads"
            owners = {item["name"]: (item["person_id"], item["rows"]) for item in check["owners"]}
            assert owners == {admin: (admin_id, 3), "Nobody Known": (None, 1)}
            # Rows 1 and 4 are new and name a teammate; row 5 repeats row 1.
            assert check["owned_new"] == 2
            fates = {item["header"]: (item["fate"], item["field"]) for item in check["columns"]}
            assert fates == {
                "Sr No": ("kept", None),
                "Customer Name": ("matched", "name"),
                "Mobile No.": ("matched", "phone"),
                "City/Town": ("matched", "city"),
                "Status": ("matched", "stage"),
                "Assigned To": ("matched", "owner"),
                "Remarks": ("kept", None),
                "lead_id": ("not_imported", None),
                "Blank": ("empty", None),
            }
            # A seller's import never reads owners: the column is only kept on the lead.
            here.as_seller()
            theirs = (
                await here.client.post(f"{BASE}/imports/check", json=body(), headers=WRITE)
            ).json()
            assert (theirs["owners"], theirs["owned_new"]) == ([], 0)
            assert {item["header"]: item["fate"] for item in theirs["columns"]}[
                "Assigned To"
            ] == "kept"
            here.as_admin()
            assert await here.leads() == 0

            # Share between my sellers: the two rows without a teammate go to the seller;
            # the file's owner keeps theirs.
            done = await here.client.post(
                f"{BASE}/imports",
                json=body(assign="people", shares=[{"person_id": seller_id, "count": 2}]),
                headers=WRITE,
            )
            assert done.status_code == 200, done.text
            result = done.json()
            assert (result["created"], result["owned"]) == (4, 2)
            assert result["unmatched_stages"] == ["Will think"]
            assert result["unmatched_owners"] == ["Nobody Known"]
            async with here.setup.sessions() as db:
                leads = {
                    lead.name: lead
                    for lead in (
                        await db.scalars(select(Lead).where(Lead.tenant_id == here.tenant_id))
                    ).all()
                }
            owner_of = {name: str(lead.owner_person_id) for name, lead in leads.items()}
            assert owner_of == {
                "Rahul Kumar Example": admin_id,
                "Sneha Patil Fresh": admin_id,
                "Pooja Sharma Sample": seller_id,
                "Amit Verma Demo": seller_id,
            }
            pooja = leads["Pooja Sharma Sample"]
            assert (pooja.stage, pooja.step, pooja.city) == ("follow_up", "open_leads", "Nashik")
            # The file's own word stays on the lead, shown with its details.
            shown = (await here.client.get(f"{BASE}/leads/{pooja.id}")).json()
            fields = {field["label"]: field["value"] for field in shown["source_fields"]}
            assert (fields["Status"], fields["Remarks"]) == ("Will think", "thoda time chahiye")

    run(exercise())
