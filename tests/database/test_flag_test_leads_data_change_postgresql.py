"""The approved data change that marks named leads as test data, reversibly
(scripts/data-changes/flag-test-leads.py; owner's review, 17 Nov 2026), on PostgreSQL: the read
reads; the dry run rehearses and leaves nothing; a wrong count or a lead from elsewhere is
refused; the apply sets only test_data on the named leads (not revision, updated_at or events)
with one audit event; a rerun changes nothing; the marked lead's call leaves the numbers; the
undo clears exactly what the run set and leaves a lead that was test data before. Made-up
people only."""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, select, update

from ac_platform.audit.models import AuditEvent
from ac_platform.identity.models import Person
from ac_platform.lead_desk.hours import IST
from ac_platform.lead_desk.models import Lead, LeadEvent
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_desk_honest_connected_postgresql import all_day, dial
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, world

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/data-changes/flag-test-leads.py"
LOADER = importlib.util.spec_from_file_location("flag_test_leads", SCRIPT)
assert LOADER is not None and LOADER.loader is not None
tool = importlib.util.module_from_spec(LOADER)
LOADER.loader.exec_module(tool)


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_read_dry_run_refusals_apply_rerun_and_undo(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            now = datetime.now(UTC)
            if (now - timedelta(minutes=10)).astimezone(IST).date() != now.astimezone(IST).date():
                pytest.skip("the calls would be yesterday's, just after midnight")
            sessions = here.setup.sessions
            async with sessions() as db:
                admin = await db.scalar(
                    select(Person.email).where(Person.id == here.setup.state.person_id)
                )
            assert admin
            await all_day(here)
            qa = UUID(await here.add("Fictional QA Phone Lead", "98760 72001"))
            earlier = UUID(await here.add("Fictional Already Test", "98760 72002"))
            real = UUID(await here.add("Fictional Real Buyer", "98760 72003"))
            await dial(here, str(qa))
            await dial(here, str(real))
            async with sessions() as db, db.begin():
                await db.execute(update(Lead).where(Lead.id == earlier).values(test_data=True))

            async def snapshot() -> dict[UUID, tuple[bool, int, datetime]]:
                async with sessions() as db:
                    rows = (
                        await db.execute(
                            select(Lead.id, Lead.test_data, Lead.revision, Lead.updated_at).where(
                                Lead.tenant_id == here.tenant_id
                            )
                        )
                    ).all()
                return {row.id: (row.test_data, row.revision, row.updated_at) for row in rows}

            async def events() -> int:
                async with sessions() as db:
                    return int(
                        await db.scalar(
                            select(func.count()).where(LeadEvent.tenant_id == here.tenant_id)
                        )
                        or 0
                    )

            async def audits(action: str) -> int:
                async with sessions() as db:
                    return int(
                        await db.scalar(
                            select(func.count()).where(
                                AuditEvent.tenant_id == here.tenant_id, AuditEvent.action == action
                            )
                        )
                        or 0
                    )

            async def calls() -> int:
                here.as_admin()
                body = (await here.client.get(f"{BASE}/reports/performance?days=1")).json()
                return int(body["current"]["calls"])

            first = await snapshot()
            first_events = await events()
            assert await calls() == 2
            spec = tool.spec_of(
                json.dumps(
                    {
                        "command_id": str(uuid4()),
                        "tenant": str(here.tenant_id),
                        "lead_ids": [str(qa), str(earlier)],
                        "expected": 2,
                        "approver_email": admin,
                        "approver": "Fictional Owner, test review",
                        "issue": "AUT-test",
                    }
                )
            )

            read = await tool.execute(sessions, spec, mode="read")
            assert read["found"] == 2 and read["marked"] == [str(earlier)[:8]]

            dry = await tool.execute(sessions, spec, mode="dry-run")
            assert dry["status"] == "rehearsed_and_rolled_back"
            assert (dry["changed"], dry["already"]) == (1, 1)
            assert await snapshot() == first

            with pytest.raises(SystemExit) as wrong:
                tool.spec_of(json.dumps({**spec, "expected": 3}))
            assert json.loads(str(wrong.value))["refused"] == "count_mismatch"
            with pytest.raises(SystemExit) as elsewhere:
                await tool.execute(
                    sessions,
                    {**spec, "lead_ids": [str(qa), str(uuid4())]},
                    mode="apply",
                )
            assert json.loads(str(elsewhere.value))["refused"] == "lead_not_in_organisation"
            assert await snapshot() == first

            applied = await tool.execute(sessions, spec, mode="apply")
            assert applied["status"] == "applied" and applied["changed_ids"] == [str(qa)[:8]]
            after = await snapshot()
            assert after[qa] == (True, first[qa][1], first[qa][2])
            assert {lead: row for lead, row in after.items() if lead != qa} == {
                lead: row for lead, row in first.items() if lead != qa
            }
            assert await events() == first_events
            assert await audits(tool.ACTION) == 1
            # The QA lead's call left the numbers; the real one still counts.
            assert await calls() == 1

            rerun = await tool.execute(sessions, spec, mode="apply")
            assert rerun["changed"] == 0
            assert await audits(tool.ACTION) == 1

            undone = await tool.execute(sessions, spec, mode="apply", undo=True)
            assert undone["changed_ids"] == [str(qa)[:8]]
            back = await snapshot()
            assert back[qa][0] is False and back[earlier][0] is True
            assert await audits(tool.UNDO_ACTION) == 1
            assert await calls() == 2
            again = await tool.execute(sessions, spec, mode="apply", undo=True)
            assert again["changed"] == 0
            assert await audits(tool.UNDO_ACTION) == 1

    run(exercise())
