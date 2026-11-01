"""A sandbox organisation hears its alerts, on PostgreSQL (hardcore phone QA ph1-39, 1 Nov 2026:
"An enquiry isn't called in 15 min" on in the sandbox, a new lead waiting for hours, and no alert
ever came: every sandbox lead is test data, which the alerts left out). Its test leads count for
the first-call and missed-call alerts and their lists; a real organisation's test leads still
never do. Made-up people and numbers only."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, update

from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
)
from ac_platform.lead_desk import owner_alerts
from ac_platform.lead_desk.models import Lead, LeadDeskSettings, LeadEvent
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import ROOT, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_a_sandbox_hears_alerts_on_its_test_leads(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            waiting = UUID(await here.add("Fictional Waiting Enquiry", "98760 68101"))
            rang = UUID(await here.add("Fictional Missed Caller", "98760 68102"))
            now = datetime.now(UTC)
            hour_ago = now - timedelta(hours=1)
            async with here.setup.sessions() as db, db.begin():
                # Both arrived an hour ago, as test data; one rang 40 minutes ago, unanswered.
                await db.execute(
                    update(Lead)
                    .where(Lead.tenant_id == here.tenant_id)
                    .values(test_data=True, created_at=hour_ago)
                )
                await db.execute(
                    update(LeadEvent)
                    .where(LeadEvent.tenant_id == here.tenant_id)
                    .values(created_at=hour_ago)
                )
                db.add(
                    LeadEvent(
                        id=uuid4(),
                        tenant_id=here.tenant_id,
                        lead_id=rang,
                        kind="call",
                        actor_person_id=here.seller.person_id,
                        data={
                            "via": "phone",
                            "direction": "missed",
                            "duration_seconds": 0,
                            "connected": False,
                        },
                        created_at=now - timedelta(minutes=40),
                    )
                )

            async def over(kind: owner_alerts.Kind) -> set[UUID]:
                async with here.setup.sessions() as db:
                    row = await db.get(LeadDeskSettings, here.tenant_id)
                    config = (row.config if row is not None else None) or {}
                    found = await owner_alerts.over_limit(db, here.tenant_id, kind, config, now=now)
                return {item.subject for item in found}

            # A real organisation: its test leads never alert.
            assert await over("first_call") == set()
            assert await over("missed_call") == set()

            async with here.setup.sessions() as db, db.begin():
                db.add(
                    ConversationSandboxOrganisation(
                        tenant_id=here.tenant_id,
                        approved_by_person_id=here.setup.state.person_id,
                        approval_reference="fictional-sandbox",
                        created_at=now,
                    )
                )
            # A sandbox: every lead is test data, and they alert as real ones would.
            assert waiting in await over("first_call")
            assert await over("missed_call") == {rang}

    run(exercise())
