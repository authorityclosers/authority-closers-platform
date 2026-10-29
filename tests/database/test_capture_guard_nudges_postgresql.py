"""A persisted, deduplicated in-app nudge without FCM or a new notification kind."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, select

from ac_platform.http.product_updates import install_product_updates_http
from ac_platform.lead_desk.capture_guard_nudges import collect
from ac_platform.lead_desk.models import LeadEvent
from ac_platform.product_updates.models import Notification
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import ROOT, WRITE, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_daily_capture_nudge_persists_once_and_excludes_private_and_simulated(
    postgres_harness: Any,
    tmp_path: Path,
):
    async def exercise():
        async with world(postgres_harness, tmp_path) as here:
            install_product_updates_http(
                here.setup.app, settings=here.setup.settings, require_actor=here.setup.require_actor
            )
            lead = UUID(await here.add("Alex Example", "+12025550123"))
            due = datetime.now(UTC).replace(hour=13, minute=30, second=0, microsecond=0)
            private = uuid4()
            async with here.setup.sessions() as db, db.begin():
                for eid, kind, data in [
                    (uuid4(), "call", {"via": "phone", "duration_seconds": 40}),
                    (uuid4(), "call", {"via": "phone", "duration_seconds": 20}),
                    (private, "call", {"via": "phone"}),
                    (uuid4(), "edited", {"private_call": str(private), "private": True}),
                    (uuid4(), "call", {"simulated": True}),
                ]:
                    db.add(
                        LeadEvent(
                            id=eid,
                            tenant_id=here.tenant_id,
                            lead_id=lead,
                            kind=kind,
                            actor_person_id=here.seller.person_id,
                            command_id=uuid4(),
                            data=data,
                            created_at=due
                            - timedelta(hours=1)
                            + (timedelta(seconds=1) if kind == "edited" else timedelta(0)),
                        )
                    )
                await db.flush()
                assert await collect(db, due - timedelta(seconds=1)) == 0
                assert await collect(db, due) == 1
            # New transaction / another worker: the ledger still suppresses a duplicate.
            async with here.setup.sessions() as db, db.begin():
                assert await collect(db, due + timedelta(minutes=1)) == 0
                notes = list(
                    (
                        await db.scalars(
                            select(Notification).where(
                                Notification.person_id == here.seller.person_id,
                                Notification.dedupe_key.like("capture-missing:%"),
                            )
                        )
                    ).all()
                )
                assert len(notes) == 1
                assert notes[0].title == "2 calls today have no recording: fix"
                assert notes[0].kind == "analysis_paused" and notes[0].urgent
                assert notes[0].href == "/settings/privacy#calls-setup"
                assert notes[0].read_at is None
            here.as_seller()
            bell = await here.client.get("/v1/notifications")
            assert bell.status_code == 200, bell.text
            entry = next(
                note for note in bell.json()["notifications"] if note["id"] == str(notes[0].id)
            )
            assert entry["urgent"] and entry["read"] is False
            unread = bell.json()["unread_count"]
            acknowledged = await here.client.post(
                "/v1/notifications/read", json={"ids": [entry["id"]]}, headers=WRITE
            )
            assert acknowledged.status_code == 200, acknowledged.text
            assert acknowledged.json()["unread_count"] == unread - 1
            refreshed = (await here.client.get("/v1/notifications")).json()
            assert next(note for note in refreshed["notifications"] if note["id"] == entry["id"])[
                "read"
            ]
            async with here.setup.sessions() as db, db.begin():
                assert await collect(db, due + timedelta(minutes=2)) == 0

    run(exercise())
