"""Undo import on PostgreSQL (competitor teardown 22, 1 Nov 2026): an owner or admin
undoes a file import within 48 hours. The leads nobody has worked go; a lead a seller
already worked stays, said with why; a number that was already a lead is never touched;
Import history shows it undone; the audit has ids and counts only. A seller can't undo,
and an import older than 48 hours can't be undone. Made-up people only."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, select

from ac_platform.audit.models import AuditEvent
from ac_platform.lead_desk import imports
from ac_platform.lead_desk.contracts import UndoImport
from ac_platform.lead_desk.imports import ImportBook
from ac_platform.lead_desk.models import Lead
from ac_platform.lead_desk.store import DeskError, LeadDesk, Viewer
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, world

NAMES = ("Asha Example", "Ravi Sample", "Meera Demo", "Kiran Sample")


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_undo_takes_back_the_untouched_leads_and_keeps_the_worked_ones(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            here.as_admin()
            known = await here.client.post(
                f"{BASE}/leads",
                json={"command_id": str(uuid4()), "name": "Kiran Sample", "phone": "98760 74009"},
                headers=WRITE,
            )
            assert known.status_code == 201, known.text

            sheet = (
                b"Name,Phone\n"
                b"Asha Example,98760 74001\n"
                b"Ravi Sample,98760 74002\n"
                b"Meera Demo,98760 74003\n"
                b"Kiran Sample,98760 74009\n"
            )
            looked = await here.client.post(
                f"{BASE}/imports/preview",
                content=sheet,
                headers={"Origin": ORIGIN, "Content-Type": "text/csv", "X-File-Name": "list.csv"},
            )
            assert looked.status_code == 200, looked.text
            seen = looked.json()
            done = await here.client.post(
                f"{BASE}/imports",
                json={
                    "command_id": str(uuid4()),
                    "file_name": "list.csv",
                    "mapping": seen["mapping"],
                    "rows": seen["rows"],
                    "side": "cold",
                    "assign": "people",
                    "shares": [{"person_id": str(here.seller.person_id), "count": 3}],
                },
                headers=WRITE,
            )
            assert done.status_code == 200, done.text
            result = done.json()
            assert (result["created"], result["repeats"]) == (3, 1)
            import_id = result["import_id"]
            assert import_id and result["undo_until"]

            async with here.setup.sessions() as db:
                rows = await db.execute(
                    select(Lead.phone, Lead.id).where(Lead.tenant_id == here.tenant_id)
                )
                phones = {phone: lead_id for phone, lead_id in rows.tuples()}
            ravi = phones["+919876074002"]
            # Import history lists it, undoable.
            history = (await here.client.get(f"{BASE}/imports")).json()["imports"]
            assert [(item["import_id"], item["file_name"], item["leads"]) for item in history] == [
                (import_id, "list.csv", 3)
            ]
            assert history[0]["undone"] is False and history[0]["undo_until"]

            # The seller works one of them: a note on Ravi.
            here.as_seller()
            noted = await here.client.post(
                f"{BASE}/leads/{ravi}/notes",
                json={"command_id": str(uuid4()), "note": "Fictional words"},
                headers=WRITE,
            )
            assert noted.status_code == 200, noted.text
            # A seller can't undo an import, nor see the history.
            refused = await here.client.post(
                f"{BASE}/imports/{import_id}/undo",
                json={"command_id": str(uuid4())},
                headers=WRITE,
            )
            assert refused.status_code == 403, refused.text
            assert (await here.client.get(f"{BASE}/imports")).json()["imports"] == []

            here.as_admin()
            command = {"command_id": str(uuid4())}
            undone = await here.client.post(
                f"{BASE}/imports/{import_id}/undo", json=command, headers=WRITE
            )
            assert undone.status_code == 200, undone.text
            answer = undone.json()
            assert answer["removed"] == 2
            assert [(item["lead_id"], item["name"], item["why"]) for item in answer["kept"]] == [
                (str(ravi), "Ravi Sample", "Has a note")
            ]
            # The same confirm again changes nothing and answers the same.
            again = await here.client.post(
                f"{BASE}/imports/{import_id}/undo", json=command, headers=WRITE
            )
            assert again.status_code == 200, again.text
            assert again.json() == answer

            async with here.setup.sessions() as db:
                left = set(
                    (
                        await db.scalars(select(Lead.phone).where(Lead.tenant_id == here.tenant_id))
                    ).all()
                )
                audit = (
                    await db.scalars(
                        select(AuditEvent).where(
                            AuditEvent.tenant_id == here.tenant_id,
                            AuditEvent.resource_type == imports.AUDIT_RESOURCE,
                        )
                    )
                ).all()
            # Asha and Meera are gone; Ravi (worked) and Kiran (already a lead) stay.
            assert "+919876074001" not in left and "+919876074003" not in left
            assert {"+919876074002", "+919876074009"} <= left
            assert len(audit) == 1
            payload = audit[0].payload
            assert payload["import_id"] == import_id
            assert (payload["deleted"], payload["kept"]) == (2, 1)
            assert payload["kept_ids"] == [str(ravi)]
            words = json.dumps(payload)
            for private in (*NAMES, "9876074", "Fictional words"):
                assert private not in words

            history = (await here.client.get(f"{BASE}/imports")).json()["imports"]
            assert [(item["leads"], item["undone"]) for item in history] == [(1, True)]

            # Older than 48 hours: refused, nothing removed, and history no longer offers it.
            admin = Viewer(
                person_id=here.setup.state.person_id,
                tenant_id=here.tenant_id,
                role="admin",
                name="",
            )
            later = datetime.now(UTC) + imports.UNDO_FOR + timedelta(hours=1)
            async with here.setup.sessions() as db, db.begin():
                book = ImportBook(LeadDesk(db, admin, now=later))
                with pytest.raises(DeskError) as late:
                    await book.undo(UUID(import_id), UndoImport(command_id=uuid4()))
                assert late.value.status == 409
                assert (await book.recent()).imports == ()
            # An import that isn't there.
            missing = await here.client.post(
                f"{BASE}/imports/{uuid4()}/undo",
                json={"command_id": str(uuid4())},
                headers=WRITE,
            )
            assert missing.status_code == 404, missing.text

    run(exercise())
