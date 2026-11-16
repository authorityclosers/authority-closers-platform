"""The approved data change that moves one person's open leads to the no-owner pool
(scripts/data-changes/leads-to-no-owner-pool.py), on PostgreSQL: the dry run rehearses and
leaves nothing; the apply leaves every open lead the person owns with no owner, each with one
"reassigned ... to nobody" line in its history, and tells nobody; a closed lead keeps its
owner; one audit event; a rerun moves nothing. Made-up people only (Wise Life and iSolar,
17 Nov 2026: their admin doesn't sell)."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, select

from ac_platform.audit.models import AuditEvent
from ac_platform.identity.models import Person
from ac_platform.lead_desk.models import Lead, LeadEvent
from ac_platform.product_updates.models import Notification
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import ROOT, world

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/data-changes/leads-to-no-owner-pool.py"
LOADER = importlib.util.spec_from_file_location("leads_to_no_owner_pool", SCRIPT)
assert LOADER is not None and LOADER.loader is not None
tool = importlib.util.module_from_spec(LOADER)
LOADER.loader.exec_module(tool)


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_open_leads_to_the_pool_quietly_closed_kept(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            sessions = here.setup.sessions
            async with sessions() as db:
                admin = await db.scalar(
                    select(Person.email).where(Person.id == here.setup.state.person_id)
                )
            assert admin
            first = await here.add("Fictional One", "98760 77001")
            second = await here.add("Fictional Two", "98760 77002")
            closed = await here.add("Fictional Won", "98760 77003")
            async with sessions() as db:
                won = await db.get(Lead, UUID(closed))
                assert won is not None
                won.stage = "won"
                await db.commit()

            async def bells() -> int:
                async with sessions() as db:
                    return int(await db.scalar(select(func.count()).select_from(Notification)) or 0)

            before = await bells()
            spec = {
                "command_id": str(uuid4()),
                "tenant": str(here.tenant_id)[:8],
                "person_id": str(here.seller.person_id),
                "approver_email": admin,
                "approver": "Fictional owner, in chat",
                "issue": "AUT-test",
                "reason": "Moved to the no-owner pool: this person doesn't sell",
            }
            now = datetime.now(UTC)
            dry = await tool.execute(sessions, spec, mode="dry-run", now=now)
            assert dry["status"] == "rehearsed_and_rolled_back"
            assert dry["before"]["open"] == 2 and dry["counts"] == {"moved": 2}
            assert dry["after"]["open"] == 0
            async with sessions() as db:
                still = await db.get(Lead, UUID(first))
                assert still is not None and still.owner_person_id == here.seller.person_id

            done = await tool.execute(sessions, spec, mode="apply", now=now)
            assert done["counts"] == {"moved": 2} and done["audited"] is True
            async with sessions() as db:
                for lead_id in (first, second):
                    lead = await db.get(Lead, UUID(lead_id))
                    assert lead is not None and lead.owner_person_id is None
                    assert lead.assigned_at is None
                    lines = (
                        await db.scalars(
                            select(LeadEvent).where(
                                LeadEvent.lead_id == lead.id, LeadEvent.kind == "reassigned"
                            )
                        )
                    ).all()
                    assert len(lines) == 1
                    assert lines[0].data["to"] is None
                    assert lines[0].data["from"] == str(here.seller.person_id)
                    assert lines[0].data["reason_text"] == spec["reason"]
                kept = await db.get(Lead, UUID(closed))
                assert kept is not None and kept.owner_person_id == here.seller.person_id
                audits = await db.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action == tool.ACTION)
                )
                assert audits == 1
            assert await bells() == before

            again = await tool.execute(sessions, spec, mode="apply", now=now)
            assert again["audited"] is False and again["before"]["open"] == 0
            read = await tool.execute(sessions, spec, mode="read", now=now)
            assert read["owned"] == {"live:won": 1}

    run(exercise())
