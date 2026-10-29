"""No-call-log capture: owned lead only, organisation gating and stable call event retries."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, update

from ac_platform.lead_desk.models import Lead
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_capture_retries_and_non_lead_rejection(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            lead = await here.add("Alex Example", "+12025550123")
            here.as_seller()
            book = await here.client.get(f"{BASE}/phone-book")
            assert book.status_code == 200, book.text
            assert book.json()["organisation_workspace"] is True
            assert book.json()["tenant_id"]
            command = dict(
                command_id=str(uuid4()),
                number="+12025550123",
                started_at=(datetime.now(UTC) - timedelta(milliseconds=1)).isoformat(),
                duration_seconds=20,
            )
            first = await here.client.post(f"{BASE}/recording-call", json=command, headers=WRITE)
            assert first.status_code == 200, first.text
            assert first.json()["lead_id"] == lead
            again = await here.client.post(f"{BASE}/recording-call", json=command, headers=WRITE)
            assert again.status_code == 200, again.text
            assert again.json()["event_id"] == first.json()["event_id"]
            unknown = await here.client.post(
                f"{BASE}/recording-call",
                json=command | {"command_id": str(uuid4()), "number": "+12025550124"},
                headers=WRITE,
            )
            assert unknown.status_code == 409, unknown.text
            assert (
                await here.client.post(f"{BASE}/recording-call", json=command)
            ).status_code == 403
            wrong_scope = await here.client.post(
                f"{BASE}/recording-call",
                json=command,
                headers=WRITE | {"X-Auto-Capture-Identity": "another:workspace"},
            )
            assert wrong_scope.status_code == 409
            detail = await here.detail(lead)
            event = next(
                event
                for event in detail["events"]
                if event.get("event_id") == first.json()["event_id"]
            )
            assert event["via"] == "dialler_recording" and event["direction"] is None
            assert event["can_hide"] is True
            private = await here.client.post(
                f"{BASE}/calls/{first.json()['event_id']}/private",
                json={"command_id": str(uuid4()), "private": True},
                headers=WRITE,
            )
            assert private.status_code == 200, private.text
            held = await here.client.post(f"{BASE}/recording-call", json=command, headers=WRITE)
            assert held.status_code == 409
            # A changed owner removes the old seller's right to send this recording.
            async with here.setup.sessions() as db, db.begin():
                await db.execute(
                    update(Lead)
                    .where(Lead.id == UUID(lead))
                    .values(owner_person_id=here.setup.state.person_id)
                )
            reassigned = await here.client.post(
                f"{BASE}/recording-call", json=command, headers=WRITE
            )
            assert reassigned.status_code == 409

    run(exercise())
