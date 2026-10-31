"""A sandbox organisation's reports count its test data (owner, 31 Oct 2026: in a sandbox
organisation every owner view fills); every other organisation's still leave test leads out.

The same test-data leads, read twice: before the organisation is marked as a sandbox
(conversation_sandbox_organisations), the Pipeline report and Performance's new leads skip
them; once it is marked, both count them. Disposable loopback PostgreSQL, fictional rows only.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import update

from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
)
from ac_platform.lead_desk.store import LeadDesk, Viewer
from ac_platform.tenancy.models import Membership
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import _setup
from tests.database.test_lead_desk_postgresql import _organisation


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_a_sandbox_counts_its_test_data_and_a_real_organisation_does_not(
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

            # Two test-data leads and one real lead, given to the seller two days ago.
            async with setup.sessions() as db, db.begin():
                desk = LeadDesk(db, owner, now=now - timedelta(days=2))
                for record, test_data in (
                    ({"name": "Fictional Test Lead", "phone": "9800000061"}, True),
                    ({"name": "Fictional Other Test Lead", "phone": "9800000062"}, True),
                    ({"name": "Fictional Real Lead", "phone": "9800000063"}, False),
                ):
                    lead, outcome = await desk.ingest(
                        record,
                        source="meta",
                        assign="person",
                        person_id=seller.person_id,
                        test_data=test_data,
                    )
                    assert outcome == "created" and lead is not None

            async def numbers() -> tuple[int, int]:
                async with setup.sessions() as db:
                    reader = LeadDesk(db, owner, now=now)
                    report = await reader.pipeline_report(days=7)
                    week = await reader.performance(7)
                return report.total, week.current.new_leads

            # A real organisation: test leads stay out of both, as before.
            assert await numbers() == (1, 1)

            # Marked as a sandbox: its test data counts in both.
            async with setup.sessions() as db, db.begin():
                db.add(
                    ConversationSandboxOrganisation(
                        tenant_id=tenant,
                        approved_by_person_id=setup.state.person_id,
                        approval_reference="test: a fictional sandbox organisation",
                        created_at=now,
                    )
                )
            assert await numbers() == (3, 3)
        finally:
            await setup.engine.dispose()

    run(exercise())
