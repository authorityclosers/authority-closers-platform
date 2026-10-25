"""The approved data change that creates a fictional test organisation
(scripts/data-changes/test-organisation.py), on PostgreSQL: a dry run that rehearses the
whole change and leaves nothing; the apply through the app's own code (an organisation with
its Owner, the template's stages, twelve fictional test-data leads over the stages without
a phone, two of them waiting unassigned and newest, a meeting booked and two held); one
audit event; a rerun that changes nothing; the read-back; and no second organisation by the
same name."""

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
from ac_platform.lead_desk.models import Lead, LeadRep
from ac_platform.tenancy.models import Organisation, Tenant
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import ROOT, world

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/data-changes/test-organisation.py"
LOADER = importlib.util.spec_from_file_location("test_organisation", SCRIPT)
assert LOADER is not None and LOADER.loader is not None
tool = importlib.util.module_from_spec(LOADER)
LOADER.loader.exec_module(tool)


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_rehearse_apply_once_audited_read_back_and_no_twin(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            sessions = here.setup.sessions
            async with sessions() as db:
                email = await db.scalar(
                    select(Person.email).where(Person.id == here.setup.state.person_id)
                )
            assert email
            spec = {
                "command_id": str(uuid4()),
                "name": "Fictional Rooftops",
                "owner_email": email,
                "approver_email": email,
                "issue": "AUT-test",
                "template": "inside_sales_demos",
            }
            options: dict[str, Any] = {"now": datetime.now(UTC), "boundaries": (uuid4(), uuid4())}

            async def count(model: Any, *where: Any) -> int:
                async with sessions() as db:
                    return int(
                        await db.scalar(select(func.count()).select_from(model).where(*where)) or 0
                    )

            # The dry run makes it all, reports it, and leaves nothing.
            dry = await tool.execute(sessions, spec, mode="dry-run", **options)
            assert dry["status"] == "rehearsed_and_rolled_back"
            assert len(dry["organisation"]["leads"]) == 12
            assert await count(Tenant, Tenant.name == "Fictional Rooftops") == 0
            assert await count(AuditEvent, AuditEvent.action == tool.ACTION) == 0

            done = await tool.execute(sessions, spec, mode="apply", **options)
            assert done["status"] == "applied"
            made = done["organisation"]
            tenant = UUID(made["tenant_id"])
            assert [member["role"] for member in made["members"]] == ["owner"]
            assert made["stages"]["industry"] == "inside_sales_demos"
            by_stage = {item["key"]: item["leads"] for item in made["stages"]["live"]}
            assert by_stage["new"] == 4
            for key in (
                "not_connected",
                "discussion_incomplete",
                "meeting_scheduled",
                "demo_completed",
                "won",
                "lost",
            ):
                assert by_stage[key] == 1, key
            assert by_stage["interested"] == 2
            assert all(lead["test_data"] for lead in made["leads"])
            # The two waiting leads are nobody's yet, and the newest.
            assert [lead["held"] for lead in made["leads"]].count(False) == 2
            assert {lead["name"] for lead in made["leads"][-2:]} == {"Lata Example", "Farhan Demo"}
            assert not any(lead["held"] for lead in made["leads"][-2:])
            assert made["meetings"] == {"scheduled": 1, "done": 2}
            assert await count(Lead, Lead.tenant_id == tenant, Lead.phone.is_not(None)) == 0
            assert await count(AuditEvent, AuditEvent.action == tool.ACTION) == 1
            async with sessions() as db:
                rep = await db.get(LeadRep, (tenant, here.setup.state.person_id))
                assert rep is not None and rep.available is False

            # A rerun changes nothing; the read-back sees what the apply made.
            again = await tool.execute(sessions, spec, mode="apply", **options)
            assert again["status"] == "already_applied"
            assert await count(Organisation, Organisation.tenant_id == tenant) == 1
            assert await count(Lead, Lead.tenant_id == tenant) == 12
            read = await tool.execute(sessions, spec, mode="read", **options)
            assert read["status"] == "read" and read["organisation"] == made

            # Another request for the same name is refused, and changes nothing.
            with pytest.raises(SystemExit):
                await tool.execute(
                    sessions, {**spec, "command_id": str(uuid4())}, mode="apply", **options
                )
            assert await count(Tenant, Tenant.name == "Fictional Rooftops") == 1

    run(exercise())
