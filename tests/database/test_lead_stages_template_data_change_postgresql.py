"""The approved data change that installs a kind of business's stages for one organisation
(scripts/data-changes/lead-stages-template.py), on PostgreSQL: a read-only dry run, the
install with its map through the app's own move, an audit event, a rerun that changes
nothing, and a map the app would refuse."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine, func, select, update

from ac_platform.audit.models import AuditEvent
from ac_platform.identity.models import Person
from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.models import Lead, LeadEvent
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, world

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/data-changes/lead-stages-template.py"
LOADER = importlib.util.spec_from_file_location("lead_stages_template", SCRIPT)
assert LOADER is not None and LOADER.loader is not None
tool = importlib.util.module_from_spec(LOADER)
LOADER.loader.exec_module(tool)


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_install_with_its_map_once_audited_and_a_rerun_changes_nothing(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            # The organisation runs on the education stages first.
            here.as_admin()
            version = (await here.client.get(f"{BASE}/journey")).json()["version"]
            picked = await here.client.post(
                f"{BASE}/journey/template",
                json={"expectedVersion": version, "template": "education"},
                headers=WRITE,
            )
            assert picked.status_code == 200, picked.text
            fresh = await here.add("Fictional Stage One", "98760 64001")
            spoke = await here.add("Fictional Stage Two", "98760 64002")
            async with here.setup.sessions() as db, db.begin():
                await db.execute(
                    update(Lead)
                    .where(Lead.id == spoke)
                    .values(stage="follow_up", step="counselled")
                )
                email = await db.scalar(
                    select(Person.email).where(Person.id == here.setup.state.person_id)
                )
            spec = {
                "command_id": str(uuid4()),
                "tenant": str(here.tenant_id)[:8],
                "approver_email": email,
                "issue": "AUT-test",
                "template": "inside_sales_demos",
                "map": {"counselled": "interested", "new": "new"},
            }
            now = datetime.now(UTC)

            async with here.setup.sessions() as db, db.begin():
                dry = await tool.run(db, spec, apply=False, now=now)
            assert dry["status"] == "eligible" and dry["approver_found"] is True
            assert {(item["from"], item["to"]): item["leads"] for item in dry["landings"]} == {
                ("New enquiry", "New Lead"): 1,
                ("Counselled", "Interested (In Follow-Up)"): 1,
            }
            assert "Fictional" not in str(dry)
            async with here.setup.sessions() as db:
                stored = await db.get(Lead, spoke)
                assert stored is not None and stored.step == "counselled"

            async with here.setup.sessions() as db, db.begin():
                done = await tool.run(db, spec, apply=True, now=now)
            assert (done["status"], done["leads_moved"]) == ("applied", 1)
            async with here.setup.sessions() as db:
                moved = await db.get(Lead, spoke)
                kept = await db.get(Lead, fresh)
                assert moved is not None and (moved.stage, moved.step) == (
                    "interested",
                    "interested",
                )
                assert kept is not None and kept.stage == "new"
                journey = await journeys.read(db, here.tenant_id)
                assert journey.industry == "inside_sales_demos"
                lines = (
                    await db.scalars(
                        select(LeadEvent).where(
                            LeadEvent.lead_id == spoke, LeadEvent.kind == "stage"
                        )
                    )
                ).all()
                assert len(lines) == 1
                audits = await db.scalar(
                    select(func.count()).where(
                        AuditEvent.action == "lead_desk.stages_template_data_change"
                    )
                )
                assert audits == 1

            async with here.setup.sessions() as db, db.begin():
                again = await tool.run(db, spec, apply=True, now=now)
            assert again["status"] == "already_applied"
            async with here.setup.sessions() as db:
                assert (await journeys.read(db, here.tenant_id)).version == journey.version

    run(exercise())


def test_a_map_the_app_refuses_is_refused_and_nothing_is_written(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            here.as_admin()
            version = (await here.client.get(f"{BASE}/journey")).json()["version"]
            picked = await here.client.post(
                f"{BASE}/journey/template",
                json={"expectedVersion": version, "template": "education"},
                headers=WRITE,
            )
            assert picked.status_code == 200, picked.text
            spec = {
                "command_id": str(uuid4()),
                "tenant": str(here.tenant_id),
                "approver_email": "nobody@example.test",
                "issue": "AUT-test",
                "template": "inside_sales_demos",
                # Lost leads may not be reopened by a data change.
                "map": {"lost": "interested"},
            }
            with pytest.raises(SystemExit) as refused:
                async with here.setup.sessions() as db, db.begin():
                    await tool.run(db, spec, apply=False, now=datetime.now(UTC))
            assert '"refused": "map"' in str(refused.value)
            spec["map"] = {}
            with pytest.raises(SystemExit) as nobody:
                async with here.setup.sessions() as db, db.begin():
                    await tool.run(db, spec, apply=True, now=datetime.now(UTC))
            assert "approver_not_found" in str(nobody.value)
            async with here.setup.sessions() as db:
                assert (await journeys.read(db, here.tenant_id)).industry == "education"

    run(exercise())
