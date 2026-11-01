"""The import's check on PostgreSQL (competitor teardown 5, 1 Nov 2026): the preview counts
rows whose number can't be read; the import skips them, a row repeated in the file and a
number already a lead, and says why for each row; Skip (the default) leaves a lead already
here as it was, Fill blanks fills only its empty details and Replace its details from the
row's filled cells, each in the lead's history; only owners and admins may fill or replace.
Made-up people only."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine, select

from ac_platform.lead_desk.models import Lead, LeadEvent
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, world

SHEET = (
    b"Name,Phone,Company,City\n"
    b"Asha Example,98760 75001,Example Solar,\n"
    b"Ravi Sample,call after 6,,\n"
    b"Meera Demo,98760 75003,,\n"
    b"Asha Again,98760 75001,,\n"
    b"Kiran Fresh,98760 75009,Sample Traders,Mumbai\n"
    b",,Only A Company,\n"
)
KIRAN = "+919876075009"


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_the_check_says_why_and_a_lead_already_here_changes_only_when_asked(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            here.as_admin()
            known = await here.client.post(
                f"{BASE}/leads",
                json={
                    "command_id": str(uuid4()),
                    "name": "Kiran Sample",
                    "phone": "98760 75009",
                    "city": "Pune",
                },
                headers=WRITE,
            )
            assert known.status_code == 201, known.text

            looked = await here.client.post(
                f"{BASE}/imports/preview",
                content=SHEET,
                headers={"Origin": ORIGIN, "Content-Type": "text/csv", "X-File-Name": "list.csv"},
            )
            assert looked.status_code == 200, looked.text
            seen = looked.json()
            # Six rows: four make or find a lead, one number can't be read, one has no name,
            # phone or email.
            assert (seen["total_rows"], seen["importable"]) == (6, 4)
            assert (seen["bad_numbers"], seen["repeats_in_file"], seen["known_leads"]) == (1, 1, 1)

            async def kiran() -> tuple[Lead, list[LeadEvent]]:
                async with here.setup.sessions() as db:
                    lead = await db.scalar(
                        select(Lead).where(Lead.tenant_id == here.tenant_id, Lead.phone == KIRAN)
                    )
                    assert lead is not None
                    events = (
                        await db.scalars(
                            select(LeadEvent)
                            .where(LeadEvent.lead_id == lead.id)
                            .order_by(LeadEvent.created_at)
                        )
                    ).all()
                return lead, list(events)

            def body(**more: Any) -> dict[str, Any]:
                return {
                    "command_id": str(uuid4()),
                    "file_name": "list.csv",
                    "mapping": seen["mapping"],
                    "rows": seen["rows"],
                    "side": "cold",
                    "assign": "none",
                    **more,
                }

            # A seller may only skip: leads already here may be anyone's.
            here.as_seller()
            refused = await here.client.post(
                f"{BASE}/imports", json=body(duplicates="fill"), headers=WRITE
            )
            assert refused.status_code == 403, refused.text

            # Skip, the default: two new leads; every other row says why.
            here.as_admin()
            done = await here.client.post(f"{BASE}/imports", json=body(), headers=WRITE)
            assert done.status_code == 200, done.text
            result = done.json()
            assert (result["created"], result["repeats"], result["skipped"]) == (2, 2, 2)
            assert result["updated"] == 0
            assert [(item["row"], item["reason"]) for item in result["skipped_rows"]] == [
                (1, "Number can't be read"),
                (3, "Repeated in the file"),
                (4, "Already a lead"),
                (5, "No name, phone or email"),
            ]
            async with here.setup.sessions() as db:
                names = set(
                    (
                        await db.scalars(select(Lead.name).where(Lead.tenant_id == here.tenant_id))
                    ).all()
                )
            assert {"Asha Example", "Meera Demo", "Kiran Sample"} <= names
            assert not names & {"Ravi Sample", "Asha Again", "Kiran Fresh", "Only A Company"}
            lead, events = await kiran()
            assert (lead.name, lead.company, lead.city, lead.repeats) == (
                "Kiran Sample",
                None,
                "Pune",
                0,
            )
            assert [event.kind for event in events if event.kind in ("repeat", "edited")] == []

            # Fill blanks: only the empty company; the city stays Pune.
            filled = await here.client.post(
                f"{BASE}/imports", json=body(duplicates="fill"), headers=WRITE
            )
            assert filled.status_code == 200, filled.text
            assert (filled.json()["created"], filled.json()["updated"]) == (0, 1)
            lead, events = await kiran()
            assert (lead.name, lead.company, lead.city) == (
                "Kiran Sample",
                "Sample Traders",
                "Pune",
            )
            edits = [event.data for event in events if event.kind == "edited"]
            assert edits == [
                {"changed": ["company"], "source": "import", "import_file": "list.csv"}
            ]

            # The same again changes nothing, and says so.
            again = await here.client.post(
                f"{BASE}/imports", json=body(duplicates="fill"), headers=WRITE
            )
            assert again.json()["updated"] == 0
            assert (4, "Already a lead with these details") in [
                (item["row"], item["reason"]) for item in again.json()["skipped_rows"]
            ]

            # Replace: the row's filled cells win; the history keeps what they replaced.
            replaced = await here.client.post(
                f"{BASE}/imports", json=body(duplicates="replace"), headers=WRITE
            )
            assert replaced.status_code == 200, replaced.text
            assert replaced.json()["updated"] == 1
            lead, events = await kiran()
            assert (lead.name, lead.company, lead.city, lead.phone) == (
                "Kiran Fresh",
                "Sample Traders",
                "Mumbai",
                KIRAN,
            )
            last = [event.data for event in events if event.kind == "edited"][-1]
            assert last["changed"] == ["name", "city"]
            assert last["replaced"] == {"name": "Kiran Sample", "city": "Pune"}

    run(exercise())
