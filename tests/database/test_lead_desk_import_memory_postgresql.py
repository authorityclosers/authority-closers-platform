"""Lead import I2 on PostgreSQL (owner's picks, 17 Nov 2026: "We'll remember this for your
next import"; study 01 §6). The importer says which stage a word that is no stage means and
who a name that is nobody on the team is; the import uses both, leaves out the columns left
out, and the workspace's next file starts from those choices. A Facebook lead form export is
recognised: its ids aren't imported and Meta's "p:" prefixes come off. Made-up people only."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine, select

from ac_platform.identity.models import Person
from ac_platform.lead_desk.models import Lead, LeadImportMemory
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def sheet(admin: str) -> bytes:
    return (
        "Sr No,Customer Name,Mobile No.,City/Town,Status,Assigned To,Remarks\n"
        f"1,Rahul Kumar Example,98760 75101,Pune,Call back,{admin},kal call karna\n"
        "2,Pooja Sharma Sample,98760 75102,Nashik,Will think,,thoda time chahiye\n"
        "3,Amit Verma Demo,98760 75103,Thane,New,Nobody Known,\n"
    ).encode()


META = (
    "id,created_time,ad_id,ad_name,adset_id,campaign_id,campaign_name,form_id,form_name,"
    "is_organic,platform,full_name,phone_number,city\n"
    "l:9001,2026-11-10T10:00:00+0530,ag:1,Expo ad,as:2,c:3,Expo Nov,f:4,Expo form,false,fb,"
    "Kiran Meta Example,p:+919876075201,Pune\n"
)


def without(rows: list[dict[str, str]], header: str) -> list[dict[str, str]]:
    return [{key: value for key, value in row.items() if key != header} for row in rows]


def test_picks_are_used_and_remembered_for_the_next_file(
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
            seller_id = str(here.seller.person_id)
            async with here.setup.sessions() as db:
                admin = await db.scalar(
                    select(Person.email).where(Person.id == here.setup.state.person_id)
                )
            assert admin

            async def preview(content: bytes, name: str) -> dict[str, Any]:
                looked = await here.client.post(
                    f"{BASE}/imports/preview",
                    content=content,
                    headers={"Origin": ORIGIN, "Content-Type": "text/csv", "X-File-Name": name},
                )
                assert looked.status_code == 200, looked.text
                return dict(looked.json())

            seen = await preview(sheet(admin), "first.csv")
            assert seen["remembered"] == [] and seen["skip"] == []
            rows = without(seen["rows"], "Sr No")
            headers = [header for header in seen["headers"] if header != "Sr No"]

            def body(**more: Any) -> dict[str, Any]:
                return {
                    "command_id": str(uuid4()),
                    "file_name": "first.csv",
                    "mapping": seen["mapping"],
                    "rows": rows,
                    "headers": headers,
                    "side": "cold",
                    **more,
                }

            picks = {
                "stages": {"Will think": "open_leads"},
                "owners": {"Nobody Known": seller_id},
            }
            checked = await here.client.post(
                f"{BASE}/imports/check", json=body(**picks), headers=WRITE
            )
            assert checked.status_code == 200, checked.text
            check = checked.json()
            stages = {item["word"]: item["stage"] for item in check["stages"]}
            assert stages["Will think"] == "open_leads"
            owners = {item["name"]: item["person_id"] for item in check["owners"]}
            assert owners["Nobody Known"] == seller_id
            # Someone not on the team can't be picked.
            stranger = await here.client.post(
                f"{BASE}/imports/check",
                json=body(owners={"Nobody Known": str(uuid4())}),
                headers=WRITE,
            )
            assert stranger.status_code == 422, stranger.text

            done = await here.client.post(
                f"{BASE}/imports",
                json=body(**picks, skipped=["Sr No"], kept=["Remarks"]),
                headers=WRITE,
            )
            assert done.status_code == 200, done.text
            result = done.json()
            assert result["created"] == 3
            assert result["unmatched_stages"] == []
            assert result["unmatched_owners"] == []
            async with here.setup.sessions() as db:
                leads = {
                    lead.name: lead
                    for lead in (
                        await db.scalars(select(Lead).where(Lead.tenant_id == here.tenant_id))
                    ).all()
                }
                memory = {
                    (row.kind, row.word): row.value
                    for row in (
                        await db.scalars(
                            select(LeadImportMemory).where(
                                LeadImportMemory.tenant_id == here.tenant_id
                            )
                        )
                    ).all()
                }
            assert leads["Pooja Sharma Sample"].step == "open_leads"
            assert str(leads["Amit Verma Demo"].owner_person_id) == seller_id
            shown = (await here.client.get(f"{BASE}/leads/{leads['Amit Verma Demo'].id}")).json()
            assert "Sr No" not in {field["label"] for field in shown["source_fields"]}
            assert memory[("column", "sr_no")] == "_skip"
            assert memory[("column", "remarks")] == "_keep"
            assert memory[("column", "city_town")] == "city"
            assert memory[("stage", "will_think")] == "open_leads"
            assert memory[("owner", "nobody_known")] == seller_id

            # The next file with the same columns starts from those choices.
            again = await preview(sheet(admin).replace(b"Will think", b"WILL THINK"), "next.csv")
            assert again["skip"] == ["Sr No"]
            assert set(again["remembered"]) >= {"Sr No", "Remarks", "City/Town"}
            assert again["mapping"]["city"] == "City/Town"
            second = await here.client.post(
                f"{BASE}/imports/check",
                json={
                    "command_id": str(uuid4()),
                    "file_name": "next.csv",
                    "mapping": again["mapping"],
                    "rows": without(again["rows"], "Sr No"),
                    "side": "cold",
                },
                headers=WRITE,
            )
            assert second.status_code == 200, second.text
            words = {item["word"]: item for item in second.json()["stages"]}
            assert (words["WILL THINK"]["stage"], words["WILL THINK"]["remembered"]) == (
                "open_leads",
                True,
            )
            names = {item["name"]: item for item in second.json()["owners"]}
            assert (names["Nobody Known"]["person_id"], names["Nobody Known"]["remembered"]) == (
                seller_id,
                True,
            )

            # A Facebook lead form export: recognised, its ids left out, "p:" taken off.
            meta = await preview(META.encode(), "expo-form.csv")
            assert meta["detected"] == "Facebook lead form"
            assert set(meta["skip"]) == {
                "ad_id",
                "adset_id",
                "campaign_id",
                "form_id",
                "is_organic",
            }
            assert meta["mapping"]["phone"] == "phone_number"
            assert meta["rows"][0]["phone_number"] == "+919876075201"
            assert meta["rows"][0]["id"] == "9001"
            assert meta["importable"] == 1

    run(exercise())
