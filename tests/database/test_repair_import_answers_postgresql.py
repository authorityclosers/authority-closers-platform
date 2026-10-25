"""The correction for imported form answers with numbers split at their commas
(scripts/data-changes/repair-import-answers.py), on PostgreSQL: the dry run leaves nothing;
the apply joins "₹15, 000" again in answers only, never in other fields or in words; one
audit event; a rerun repairs nothing and writes no audit event. Made-up people only."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, select, update

from ac_platform.audit.models import AuditEvent
from ac_platform.identity.models import Person
from ac_platform.lead_desk.models import Lead
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import ROOT, world

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/data-changes/repair-import-answers.py"
LOADER = importlib.util.spec_from_file_location("repair_import_answers", SCRIPT)
assert LOADER is not None and LOADER.loader is not None
tool = importlib.util.module_from_spec(LOADER)
LOADER.loader.exec_module(tool)

SPLIT = {
    "What is your current monthly income?": "₹15, 000 – ₹30, 000",
    "What would you like to improve?": "Reduce wasted leads, scale my sales process",
    "Received on the form": "19 May 2026, 20:16 IST",
}


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_numbers_in_answers_joined_once(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            lead_id = UUID(await here.add("Fictional Answers", "98760 74001"))
            other_id = UUID(await here.add("Fictional Other", "98760 74002"))
            async with here.setup.sessions() as db, db.begin():
                for lead, label in ((lead_id, "File: Fictional / Sheet1"), (other_id, "Manual")):
                    await db.execute(
                        update(Lead)
                        .where(Lead.id == lead)
                        .values(source_label=label, payload=dict(SPLIT))
                    )
                email = await db.scalar(
                    select(Person.email).where(Person.id == here.setup.state.person_id)
                )
            spec = {
                "command_id": str(uuid4()),
                "tenant": str(here.tenant_id),
                "label_prefix": "File: Fictional / ",
                "approver_email": email,
                "issue": "AUT-test",
            }
            now = datetime.now(UTC)

            async def payload(lead: UUID) -> dict[str, Any]:
                async with here.setup.sessions() as db:
                    stored = await db.get(Lead, lead)
                    assert stored is not None
                    return dict(stored.payload)

            dry = await tool.execute(here.setup.sessions, spec, mode="dry-run", now=now)
            assert dry["repaired"] == 1
            assert await payload(lead_id) == SPLIT

            done = await tool.execute(here.setup.sessions, spec, mode="apply", now=now)
            assert done["questions"] == {"What is your current monthly income?": 1}
            fixed = await payload(lead_id)
            assert fixed["What is your current monthly income?"] == "₹15,000 – ₹30,000"
            assert (
                fixed["What would you like to improve?"] == SPLIT["What would you like to improve?"]
            )
            assert fixed["Received on the form"] == SPLIT["Received on the form"]
            # A lead with another label is not this import's.
            assert await payload(other_id) == SPLIT

            again = await tool.execute(here.setup.sessions, spec, mode="apply", now=now)
            assert again["repaired"] == 0 and again["audited"] is False
            async with here.setup.sessions() as db:
                audits = await db.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action == tool.ACTION)
                )
            assert audits == 1

    run(exercise())
