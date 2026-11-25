"""Call upload is required for sellers, and Admin can measure it (owner, 17 Nov 2026 app
review: "upload/analysis required"). Fictional people only.

- A seller (member) must go through the capture setup; an admin who doesn't call leads is
  never held at it, and is once they call a lead themselves.
- The upload funnel counts sellers calling, set up with uploads on and uploading, and the
  calls seen and uploaded; test leads are left out. Counts only.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, update

from ac_platform.audit.service import AuditRepository
from ac_platform.call_ai import capture_setup, upload_funnel
from ac_platform.call_ai.capture_setup_http import install_capture_setup_http
from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.models import Lead, LeadEvent
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import ROOT, world

SETUP = "/v1/sales-xray/call-ai/capture-setup"


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def _call(tenant: UUID, lead: UUID, person: UUID, at: datetime, **data: Any) -> LeadEvent:
    return LeadEvent(
        id=uuid4(),
        tenant_id=tenant,
        lead_id=lead,
        kind="call",
        actor_person_id=person,
        command_id=uuid4(),
        data=data,
        created_at=at,
    )


def test_sellers_must_and_admins_only_once_they_call(postgres_harness: Any, tmp_path: Path):
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            setup = here.setup
            settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            install_capture_setup_http(
                setup.app, RouteContext(settings, setup.require_actor, setup.sessions)
            )
            lead = UUID(await here.add("Asha Example", "+12025550141"))

            here.as_seller()
            seller = (await here.client.get(SETUP)).json()
            assert (seller["workspace"], seller["required"]) == ("organisation", True)

            here.as_admin()
            admin = (await here.client.get(SETUP)).json()
            assert (admin["workspace"], admin["required"]) == ("organisation", False)

            # The admin calls a lead: from then on they go through it like a seller.
            async with setup.sessions() as db, db.begin():
                db.add(
                    _call(
                        setup.state.tenant_id,
                        lead,
                        setup.state.person_id,
                        datetime.now(UTC) - timedelta(hours=1),
                        via="phone",
                        duration_seconds=30,
                    )
                )
            admin = (await here.client.get(SETUP)).json()
            assert admin["required"] is True

    run(exercise())


def test_the_upload_funnel_counts_calls_seen_and_uploaded(postgres_harness: Any, tmp_path: Path):
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            setup = here.setup
            tenant = setup.state.tenant_id
            seller = here.seller.person_id
            admin = setup.state.person_id
            real = UUID(await here.add("Ravi Example", "+12025550142"))
            test = UUID(await here.add("Test Example", "+12025550143"))
            now = datetime.now(UTC)
            at = now - timedelta(hours=2)
            # The funnel counts every organisation: other tests share this database.
            async with setup.sessions() as db:
                before = await upload_funnel.read(db, now=now, window="7d")
            async with setup.sessions() as db, db.begin():
                await db.execute(update(Lead).where(Lead.id == test).values(test_data=True))
                uploaded = _call(tenant, real, seller, at, via="phone", duration_seconds=40)
                db.add_all(
                    [
                        uploaded,
                        # Its recording, a later row naming the call.
                        _call(
                            tenant,
                            real,
                            seller,
                            at + timedelta(minutes=3),
                            for_call=str(uploaded.id),
                            recording=True,
                        ),
                        # The admin's call: seen, never uploaded.
                        _call(tenant, real, admin, at, via="phone", duration_seconds=25),
                        # Not counted: not connected, a sample, a call in, a test lead.
                        _call(tenant, real, seller, at, via="phone", duration_seconds=0),
                        _call(tenant, real, seller, at, simulated=True, duration_seconds=50),
                        _call(tenant, real, seller, at, direction="missed", duration_seconds=9),
                        _call(tenant, test, seller, at, via="phone", duration_seconds=60),
                        # Older than the window.
                        _call(tenant, real, seller, now - timedelta(days=9), duration_seconds=70),
                    ]
                )
                # The seller finished setup on a phone with uploads on.
                await AuditRepository(db).append(
                    tenant_id=tenant,
                    actor_person_id=seller,
                    session_id=None,
                    action=capture_setup.ACTION,
                    resource_type=capture_setup.RESOURCE_TYPE,
                    resource_id=str(seller),
                    payload={
                        "outcome": "completed",
                        "device": "install-fictional-9",
                        "uploads": True,
                    },
                    reason="Finished call capture setup on a phone.",
                    now=at,
                )
            async with setup.sessions() as db:
                found = await upload_funnel.read(db, now=now, window="7d")
            assert found["schema"] == upload_funnel.SCHEMA

            def added(part: str, key: str) -> int:
                return int(found[part][key]) - int(before[part][key])

            assert (added("calls", "seen"), added("calls", "uploaded")) == (2, 1)
            # The seller and the admin call; only the seller is set up with uploads on,
            # and only the seller uploaded.
            assert [
                added("sellers", key)
                for key in ("calling", "uploads_on", "uploaded", "uploads_on_all")
            ] == [2, 1, 1, 1]
            assert found["truncated"] is False

    run(exercise())
