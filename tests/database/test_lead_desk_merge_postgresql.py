"""Merging duplicate leads on PostgreSQL (docs/product/lead-desk/duplicates.md, D3):
- the lead with the most human work is kept, and the other's history and tasks move to it;
- its empty fields fill from the other, the furthest stage is kept, the other closes as
  Junk "merged" and points to the kept one;
- with two sellers active, the most recent has it and the other is named;
- an open task written twice becomes one; the bookkeeping moves are never progress or a
  conversion; one audit event; a retry is one merge; a seller may not merge;
- a new record with the merged lead's phone joins the kept lead;
- an unmerge puts it all back.
Made-up people only."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, select, update

from ac_platform.audit.models import AuditEvent
from ac_platform.lead_desk.journey.transitions import stages_changed
from ac_platform.lead_desk.models import Lead, LeadEvent, LeadTask
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_lead_desk_tasks_postgresql import task
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, later, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_merge_keeps_the_story_and_an_unmerge_puts_it_back(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            kept = await here.add("Fictional Twin", "98760 79001")
            other = await here.add("Fictional Twin", "98760 79002")
            due = later(days=1)
            await task(here, kept, starts_at=due)
            await task(here, other, starts_at=due)
            kavya = (
                await seed(here.setup.engine, tenant_id=here.setup.state.tenant_id, role="member")
            ).person_id
            seller = here.seller.person_id
            stored = await here.stored(kept)
            now = stored.created_at
            async with here.setup.sessions() as db, db.begin():
                await db.execute(
                    update(Lead)
                    .where(Lead.id == UUID(other))
                    .values(
                        owner_person_id=kavya,
                        email="twin@example.com",
                        stage="interested",
                        step="interested",
                    )
                )
                await db.execute(
                    update(LeadTask)
                    .where(LeadTask.lead_id == UUID(other))
                    .values(owner_person_id=kavya)
                )
                for lead, actor, at in (
                    (kept, seller, now),
                    (kept, seller, now + timedelta(minutes=1)),
                    (other, kavya, now - timedelta(days=1)),
                ):
                    db.add(
                        LeadEvent(
                            id=uuid4(),
                            tenant_id=here.tenant_id,
                            lead_id=UUID(lead),
                            kind="note",
                            actor_person_id=actor,
                            data={"text": "Fictional note"},
                            created_at=at,
                        )
                    )

            async def events(lead: str) -> list[LeadEvent]:
                return await here.events(lead)

            before_other = len(await events(other))
            command = {"command_id": str(uuid4()), "lead_ids": [other, kept]}
            refused = await here.client.post(
                f"{BASE}/duplicates/merge", json=command, headers=WRITE
            )
            assert refused.status_code == 403
            here.as_admin()
            merged = await here.client.post(f"{BASE}/duplicates/merge", json=command, headers=WRITE)
            assert merged.status_code == 200, merged.text
            view = merged.json()
            assert view["kept_lead_id"] == kept and view["merged_lead_id"] == other
            assert view["owner_person_id"] == str(seller) and view["owner_why"] == "asked"
            assert len(view["also_worked"]) == 1 and "also worked" in view["owner_reason"]
            again = await here.client.post(f"{BASE}/duplicates/merge", json=command, headers=WRITE)
            assert again.json()["merge_id"] == view["merge_id"]

            gone, kept_lead = await here.stored(other), await here.stored(kept)
            assert gone.merged_into_id == UUID(kept) and gone.stage == "junk"
            assert gone.outcome_reason == "merged"
            assert kept_lead.email == "twin@example.com" and kept_lead.stage == "interested"
            assert kept_lead.owner_person_id == seller
            # The other lead's story is on the kept lead; the other keeps its closing lines.
            assert len(await events(other)) <= 3
            assert len(await events(kept)) >= before_other
            async with here.setup.sessions() as db:
                tasks = (
                    await db.scalars(select(LeadTask).where(LeadTask.lead_id == UUID(kept)))
                ).all()
                stage_moves = (
                    await db.scalars(
                        select(LeadEvent).where(
                            LeadEvent.tenant_id == here.tenant_id, LeadEvent.kind == "stage"
                        )
                    )
                ).all()
                audits = await db.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action == "lead_desk.leads_merged")
                )
            assert sorted(item.status for item in tasks) == ["cancelled", "open"]
            merge_moves = [e for e in stage_moves if (e.data or {}).get("source") == "merge"]
            assert len(merge_moves) == 2 and all(stages_changed(e.data) for e in merge_moves)
            assert audits == 1

            # A new record with the merged lead's phone joins the kept lead.
            joined = await here.client.post(
                f"{BASE}/leads",
                json={"command_id": str(uuid4()), "name": "Fictional Twin", "phone": "98760 79002"},
                headers=WRITE,
            )
            assert joined.status_code == 201, joined.text
            assert joined.json()["lead"]["lead_id"] == kept

            undone = await here.client.post(
                f"{BASE}/merges/{view['merge_id']}/undo",
                json={"command_id": str(uuid4())},
                headers=WRITE,
            )
            assert undone.status_code == 200, undone.text
            assert undone.json()["undone_at"] is not None
            gone, kept_lead = await here.stored(other), await here.stored(kept)
            assert gone.merged_into_id is None and gone.stage == "interested"
            assert kept_lead.email is None and kept_lead.stage == "new"
            async with here.setup.sessions() as db:
                back = (
                    await db.scalars(select(LeadTask).where(LeadTask.lead_id == UUID(other)))
                ).all()
            assert [item.status for item in back] == ["open"]
            assert len(await events(other)) > 3

    run(exercise())
