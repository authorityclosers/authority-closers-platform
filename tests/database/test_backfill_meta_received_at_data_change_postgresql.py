"""The approved data change that gives Meta leads filed before 26 Oct 2026 Meta's own time
(scripts/data-changes/backfill-meta-received-at.py; Shivam's review, 17 Nov 2026), on
PostgreSQL: the dry run rehearses and leaves nothing; a different count is refused; the apply
sets only received_at, to Meta's time (or the filing time when Meta's is later), on Meta leads
without one; a lead that has one, a lead with no readable Meta time and a lead from another
source are left alone; one audit event; a rerun changes nothing. Made-up people only."""

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
from ac_platform.lead_desk.models import Lead
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import ROOT, world

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/data-changes/backfill-meta-received-at.py"
LOADER = importlib.util.spec_from_file_location("backfill_meta_received_at", SCRIPT)
assert LOADER is not None and LOADER.loader is not None
tool = importlib.util.module_from_spec(LOADER)
LOADER.loader.exec_module(tool)


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_dry_run_refusal_apply_and_rerun(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            sessions = here.setup.sessions
            async with sessions() as db:
                admin = await db.scalar(
                    select(Person.email).where(Person.id == here.setup.state.person_id)
                )
            assert admin
            old = UUID(await here.add("Fictional Old Meta", "98760 74001"))
            later = UUID(await here.add("Fictional Clock Ahead", "98760 74002"))
            kept = UUID(await here.add("Fictional Already Timed", "98760 74003"))
            unreadable = UUID(await here.add("Fictional No Time", "98760 74004"))
            manual = UUID(await here.add("Fictional By Hand", "98760 74005"))
            async with sessions() as db, db.begin():
                filed = {
                    lead.id: lead
                    for lead in (
                        await db.scalars(select(Lead).where(Lead.tenant_id == here.tenant_id))
                    ).all()
                }
                made = filed[old].created_at
                meta_old = (made - timedelta(days=3)).astimezone(UTC).replace(microsecond=0)
                meta_late = (made + timedelta(hours=2)).astimezone(UTC).replace(microsecond=0)

                def meta(when: datetime | str) -> dict[str, Any]:
                    stamp = (
                        when if isinstance(when, str) else when.strftime("%Y-%m-%dT%H:%M:%S+0000")
                    )
                    return {"leadgen_id": "fictional", "meta": {"created_time": stamp}}

                for lead_id, payload, received in (
                    (old, meta(meta_old), None),
                    (later, meta(meta_late), None),
                    (kept, meta(meta_old), made),
                    (unreadable, meta("yesterday"), None),
                ):
                    await db.execute(
                        update(Lead)
                        .where(Lead.id == lead_id)
                        .values(source="meta", payload=payload, received_at=received)
                    )
                await db.execute(update(Lead).where(Lead.id == manual).values(received_at=None))
            async with sessions() as db:
                stamps = {
                    lead.id: (lead.revision, lead.updated_at)
                    for lead in (
                        await db.scalars(select(Lead).where(Lead.tenant_id == here.tenant_id))
                    ).all()
                }

            async def received() -> dict[UUID, datetime | None]:
                async with sessions() as db:
                    rows = (
                        await db.execute(
                            select(Lead.id, Lead.received_at).where(
                                Lead.tenant_id == here.tenant_id
                            )
                        )
                    ).all()
                return {row.id: row.received_at for row in rows}

            spec = {
                "command_id": str(uuid4()),
                "tenant": str(here.tenant_id),
                "expected": 2,
                "approver_email": admin,
                "issue": "AUT-test",
            }
            read = await tool.execute(sessions, spec, mode="read")
            assert read["left_before"] == {str(here.tenant_id)[:8]: 2}

            dry = await tool.execute(sessions, spec, mode="dry-run")
            assert dry["status"] == "rehearsed_and_rolled_back"
            assert dry["changed"] == {str(here.tenant_id)[:8]: 2}
            assert (await received())[old] is None

            with pytest.raises(SystemExit) as refused:
                await tool.execute(sessions, {**spec, "expected": 3}, mode="apply")
            assert json.loads(str(refused.value))["refused"] == "count_mismatch"
            assert (await received())[old] is None

            done = await tool.execute(sessions, spec, mode="apply")
            assert done["status"] == "applied" and done["matched"] == 2
            now = await received()
            assert now[old] == meta_old
            # Meta's time can't be after Sales X-Ray filed it: the filing time stays.
            assert now[later] == filed[later].created_at
            assert now[kept] == made
            assert now[unreadable] is None and now[manual] is None
            async with sessions() as db:
                after = {
                    lead.id: (lead.revision, lead.updated_at)
                    for lead in (
                        await db.scalars(select(Lead).where(Lead.tenant_id == here.tenant_id))
                    ).all()
                }
                audits = await db.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action == tool.ACTION)
                )
            assert after == stamps
            assert audits == 1

            again = await tool.execute(sessions, spec, mode="apply")
            assert again["matched"] == 0 and again["changed"] == {}
            left = await tool.execute(sessions, spec, mode="read")
            assert left["left_before"] == {}

    run(exercise())


def test_input_is_checked() -> None:
    base = {
        "command_id": str(uuid4()),
        "expected": 1,
        "approver_email": "owner@example.test",
        "issue": "AUT-test",
    }
    assert tool.spec_of(json.dumps(base))["expected"] == 1
    with pytest.raises(SystemExit) as refused:
        tool.spec_of(json.dumps({k: v for k, v in base.items() if k != "issue"}))
    assert json.loads(str(refused.value)) == {"refused": "missing_input", "fields": ["issue"]}
    with pytest.raises(SystemExit) as refused:
        tool.spec_of(json.dumps({**base, "expected": -1}))
    assert json.loads(str(refused.value))["refused"] == "expected_must_not_be_negative"
    assert tool.decide(0, 5) == "rerun"
    assert tool.decide(2, 2) == "fill"


def test_the_sql_sets_only_received_at_on_meta_leads_without_one() -> None:
    sql = str(tool.FILL).lower()
    assert sql.startswith("update lead_desk_leads set received_at = least(")
    head = sql.split(" where ")[0]
    for column in ("stage", "owner_person_id", "revision", "updated_at", "payload"):
        assert f"{column} =" not in head
    assert "source = 'meta' and received_at is null" in sql
