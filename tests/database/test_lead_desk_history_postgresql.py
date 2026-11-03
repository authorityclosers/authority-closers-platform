"""Old leads kept as history (owner, 2 Nov 2026): an owner brings already-worked leads into
Sales X-Ray for history. They never sit in a work list, a tab's count, the badge, Home's
queue or "Start calling"; only the Old leads filter and a search find them. The pipeline
report counts them in All time only, by campaign (a file of old leads reads Ended), and an
owner can mark a campaign Live, Paused or Ended. Disposable loopback PostgreSQL, fictional
rows only."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import update

from ac_platform.lead_desk import campaigns
from ac_platform.lead_desk.contracts import CampaignStatusCommand
from ac_platform.lead_desk.errors import DeskError
from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.store import LeadDesk, Viewer
from ac_platform.tenancy.models import Membership
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import _setup
from tests.database.test_lead_desk_postgresql import _organisation


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


OLD = (
    ("Fictional Old Buyer", "9800000071", "Poona", "won"),
    ("Fictional Old Keen", "9800000072", "pune city", "interested"),
    ("Fictional Old Untouched", "9800000073", "Baramati, Pune", "new"),
)


def test_history_leads_stay_out_of_work_and_count_in_all_time(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            async with setup.sessions() as db, db.begin():
                await db.execute(
                    update(Membership)
                    .where(Membership.person_id == setup.state.person_id)
                    .values(role="owner")
                )
            tenant = setup.state.tenant_id
            seller = await seed(setup.engine, tenant_id=tenant, role="member")
            now = datetime.now(UTC)
            owner = Viewer(person_id=setup.state.person_id, tenant_id=tenant, role="owner", name="")
            mine = Viewer(person_id=seller.person_id, tenant_id=tenant, role="member", name="")

            # One live enquiry for the seller, and three old leads brought in as history with
            # their own enquiry day, stage and salesperson.
            async with setup.sessions() as db, db.begin():
                desk = LeadDesk(db, owner, now=now - timedelta(days=1))
                live, outcome = await desk.ingest(
                    {"name": "Fictional New Enquiry", "phone": "9800000070"},
                    source="meta",
                    assign="person",
                    person_id=seller.person_id,
                )
                assert outcome == "created" and live is not None
                key = (await desk._pipeline(journeys.MAIN_PIPELINE)).key
                journey = await desk._labels(key)
                for name, phone, city, kind in OLD:
                    lead, outcome = await desk.ingest(
                        {"name": name, "phone": phone, "city": city},
                        source="csv",
                        source_label="Fictional Old CRM",
                        assign="person",
                        person_id=seller.person_id,
                        received_at=now - timedelta(days=120),
                        as_is=True,
                    )
                    assert outcome == "created" and lead is not None
                    lead.pipeline = "history"
                    if kind != "new":
                        stage = next(item for item in journey.board() if item.kind == kind)
                        desk.to_stage(
                            lead,
                            journey,
                            stage,
                            note=None,
                            command_id=uuid4(),
                            source="import",
                            via="api",
                        )
                await db.flush()

            async with setup.sessions() as db:
                desk = LeadDesk(db, mine, now=now)
                # The seller's lists, counts, badge, Home and "Start calling": the live lead only.
                inbound = await desk.leads(
                    scope="mine", stage=None, search=None, offset=0, side="inbound"
                )
                assert [row.name for row in inbound.leads] == ["Fictional New Enquiry"]
                assert inbound.view_counts == {"to_call": 1, "follow_ups": 0, "all": 1}
                cold = await desk.leads(
                    scope="mine", stage=None, search=None, offset=0, side="cold"
                )
                assert cold.total == 0
                everything = await desk.leads(scope="mine", stage=None, search=None, offset=0)
                assert everything.total == 1
                badge = await desk.badge()
                assert badge.to_call == 1
                home = await desk.desk()
                assert [row.name for row in home.queue] == ["Fictional New Enquiry"]
                next_lead = await desk.next_lead()
                assert next_lead is not None and next_lead.lead.name == "Fictional New Enquiry"

                # The Old leads filter lists them; a search finds them beside the live lead.
                old = await desk.leads(
                    scope="mine",
                    stage=None,
                    search=None,
                    offset=0,
                    side="inbound",
                    created="history",
                )
                assert sorted(row.name for row in old.leads) == sorted(item[0] for item in OLD)
                found = await desk.leads(
                    scope="mine", stage=None, search="Fictional", offset=0, side="inbound"
                )
                assert found.total == 4

            async with setup.sessions() as db:
                desk = LeadDesk(db, owner, now=now)
                month = await desk.pipeline_report(days=30)
                assert (month.total, month.history_leads) == (1, 0)
                ever = await desk.pipeline_report(days=0)
                assert (ever.total, ever.history_leads) == (4, 3)
                rows = {row.label: row for row in ever.campaigns}
                old_crm = rows["Fictional Old CRM"]
                assert (old_crm.status, old_crm.history) == ("ended", True)
                assert (old_crm.leads, old_crm.won, old_crm.interested) == (3, 1, 2)
                # No first-call time is made up for leads worked before Sales X-Ray.
                assert old_crm.first_response_minutes is None
                assert {row.status for row in ever.campaigns if not row.history} == {"live"}
                assert [(city.label, city.count) for city in ever.cities] == [
                    ("Pune", 2),
                    ("Baramati", 1),
                ]
                revision = ever.revision
                meta_key = next(row.key for row in ever.campaigns if row.source == "meta")

            # An owner pauses the live campaign; a stale revision is refused.
            async with setup.sessions() as db, db.begin():
                desk = LeadDesk(db, owner, now=now)
                saved = await desk.set_campaign_status(
                    CampaignStatusCommand(key=meta_key, status="paused", expected_revision=revision)
                )
                assert saved == revision + 1
            async with setup.sessions() as db, db.begin():
                desk = LeadDesk(db, owner, now=now)
                with pytest.raises(DeskError) as stale:
                    await desk.set_campaign_status(
                        CampaignStatusCommand(
                            key=meta_key, status="live", expected_revision=revision
                        )
                    )
                assert stale.value.status == 409
            async with setup.sessions() as db:
                desk = LeadDesk(db, owner, now=now)
                again = await desk.pipeline_report(days=0)
                assert {row.key: row.status for row in again.campaigns}[meta_key] == "paused"
                _, config = await desk.settings()
                assert campaigns.statuses(config) == {meta_key: "paused"}

            # A seller can't set a campaign's status.
            async with setup.sessions() as db, db.begin():
                desk = LeadDesk(db, mine, now=now)
                with pytest.raises(DeskError):
                    await desk.set_campaign_status(
                        CampaignStatusCommand(
                            key=meta_key, status="ended", expected_revision=revision + 1
                        )
                    )
        finally:
            await setup.engine.dispose()

    run(exercise())
