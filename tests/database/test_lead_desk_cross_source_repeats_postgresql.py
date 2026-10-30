"""One person, several sources: one lead (owner, 30 Oct 2026: "duplicate leads can be generated
via web, Google Ads and FB, we need to make sure that does not clash").

The same person fills the website form, then a Google Ads lead form, then a Facebook form. Every
source files through the same intake, so they stay one lead: its seller keeps it, each later
form is a repeat in its history naming where it came from, and the lead comes back to call now.
A form with no phone joins the lead with the same email. Disposable loopback PostgreSQL,
fictional rows only.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import func, select

from ac_platform.lead_desk.connectors.google_ads import LABEL as GOOGLE_ADS_LABEL
from ac_platform.lead_desk.models import Lead, LeadEvent
from ac_platform.lead_desk.store import LeadDesk, Viewer
from ac_platform.lead_desk.websites import SOURCE_LABEL as WEBSITE_LABEL
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import _setup
from tests.database.test_lead_desk_postgresql import _organisation


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_one_person_from_the_website_google_ads_and_facebook_is_one_lead(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            tenant = setup.state.tenant_id
            seller = await seed(setup.engine, tenant_id=tenant, role="member")
            admin = Viewer(person_id=setup.state.person_id, tenant_id=tenant, role="admin", name="")
            first = datetime.now(UTC) - timedelta(hours=2)

            # The website form comes first and the lead goes to the seller.
            async with setup.sessions() as db, db.begin():
                lead, outcome = await LeadDesk(db, admin, now=first).ingest(
                    {
                        "name": "Fictional Web Visitor",
                        "phone": "+91 98000 00071",
                        "email": "web.visitor@example.com",
                    },
                    source="webhook",
                    source_label=f"{WEBSITE_LABEL} · fictional-site.example",
                    assign="person",
                    person_id=seller.person_id,
                )
                assert outcome == "created" and lead is not None
                web_lead = lead.id

            # Then Google Ads and Facebook, the number written their own ways: the same lead.
            later = first + timedelta(hours=1)
            async with setup.sessions() as db, db.begin():
                desk = LeadDesk(db, admin, now=later)
                for record, source, label in (
                    (
                        {"full_name": "F. Web Visitor", "phone_number": "9800000071"},
                        "webhook",
                        GOOGLE_ADS_LABEL,
                    ),
                    (
                        {"name": "Web Visitor", "phone": "+919800000071", "city": "Pune"},
                        "meta",
                        "Facebook form",
                    ),
                ):
                    again, outcome = await desk.ingest(record, source=source, source_label=label)
                    assert outcome == "repeat", label
                    assert again is not None and again.id == web_lead, label

            # A form with no phone and the same email is the same person too.
            last = later + timedelta(minutes=5)
            async with setup.sessions() as db, db.begin():
                again, outcome = await LeadDesk(db, admin, now=last).ingest(
                    {"name": "Web Visitor", "email": "web.visitor@example.com"},
                    source="webhook",
                    source_label=GOOGLE_ADS_LABEL,
                )
                assert outcome == "repeat" and again is not None and again.id == web_lead

            async with setup.sessions() as db:
                count = await db.scalar(
                    select(func.count()).select_from(Lead).where(Lead.tenant_id == tenant)
                )
                stored = await db.scalar(
                    select(Lead).where(Lead.tenant_id == tenant, Lead.id == web_lead)
                )
                repeats = (
                    await db.scalars(
                        select(LeadEvent)
                        .where(LeadEvent.lead_id == web_lead, LeadEvent.kind == "repeat")
                        .order_by(LeadEvent.created_at)
                    )
                ).all()
            assert count == 1
            assert stored is not None
            # The seller keeps the lead; it comes back to call now and gains the city.
            assert stored.owner_person_id == seller.person_id
            assert stored.repeats == 3
            assert stored.next_action_at is not None and stored.next_action_at <= last
            assert stored.city == "Pune"
            assert stored.source_label == f"{WEBSITE_LABEL} · fictional-site.example"
            assert [event.data["source_label"] for event in repeats] == [
                GOOGLE_ADS_LABEL,
                "Facebook form",
                GOOGLE_ADS_LABEL,
            ]
        finally:
            await setup.engine.dispose()

    run(exercise())
