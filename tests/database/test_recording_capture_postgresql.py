"""No-call-log capture: owned lead only, organisation gating and stable call event retries."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, select, update

from ac_platform.lead_desk.models import Lead, LeadEvent
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


def test_recordings_fill_the_sellers_own_dials_once(postgres_harness: Any, tmp_path: Path) -> None:
    """Attempts with no outcome are filled in from the phone's recordings (owner via the
    orchestrator, 2 Nov 2026): only the seller's own dials, once each, beside the dial."""

    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            lead = await here.add("Alex Example", "+12025550123")
            quiet = await here.add("Bea Example", "+12025550124")
            here.as_seller()
            dialled = await here.client.post(
                f"{BASE}/leads/{lead}/calls/phone",
                json={"command_id": str(uuid4()), "duration_seconds": 90},
                headers=WRITE,
            )
            assert dialled.status_code == 200, dialled.text
            dial = next(e["event_id"] for e in dialled.json()["events"] if e["kind"] == "call")
            now = datetime.now(UTC)
            device = str(uuid4())

            def recording(key: str, number: str, ago: timedelta) -> dict[str, Any]:
                return {
                    "key": key,
                    "number": number,
                    "started_at": (now - ago).isoformat(),
                    "duration_seconds": 45,
                }

            body = {
                "device_id": device,
                "source": "recording",
                "calls": [
                    # Connected 30 s after the Call button: this dial's outcome.
                    recording("rec-1", "+12025550123", timedelta(seconds=60)),
                    # No dial on this lead: the recording adds nothing.
                    recording("rec-2", "+12025550124", timedelta(seconds=60)),
                    # Older than 30 days.
                    recording("rec-3", "+12025550123", timedelta(days=31)),
                ],
            }
            refused = await here.client.post(f"{BASE}/call-outcomes", json=body)
            assert refused.status_code == 403
            sent = await here.client.post(f"{BASE}/call-outcomes", json=body, headers=WRITE)
            assert sent.status_code == 200, sent.text
            counts = ("filled", "already", "unmatched")
            assert tuple(sent.json()[name] for name in counts) == (1, 0, 2)
            assert sent.json()["calls"] == [{"key": "rec-1", "lead_id": lead, "event_id": dial}]
            # Sent again after a dropped answer: known, and still named.
            again = await here.client.post(f"{BASE}/call-outcomes", json=body, headers=WRITE)
            assert tuple(again.json()[name] for name in counts) == (0, 1, 2)
            assert again.json()["calls"] == sent.json()["calls"]
            # From another phone, the same dial already has its outcome.
            other_phone = await here.client.post(
                f"{BASE}/call-outcomes", json=body | {"device_id": str(uuid4())}, headers=WRITE
            )
            assert tuple(other_phone.json()[name] for name in counts) == (0, 1, 2)
            wrong_scope = await here.client.post(
                f"{BASE}/call-outcomes",
                json=body,
                headers=WRITE | {"X-Auto-Capture-Identity": "another:workspace"},
            )
            assert wrong_scope.status_code == 409

            async with here.setup.sessions() as db:
                rows = (
                    await db.execute(
                        select(LeadEvent.lead_id, LeadEvent.kind, LeadEvent.data).where(
                            LeadEvent.lead_id.in_([UUID(lead), UUID(quiet)])
                        )
                    )
                ).all()
            # The dial never changes; its seconds sit beside it once, with where they came from.
            calls = [(str(lead_id), data) for lead_id, kind, data in rows if kind == "call"]
            assert [lead_id for lead_id, _ in calls] == [lead]
            assert "timed_call" not in calls[0][1] and "phone_seconds" not in calls[0][1]
            assert [
                data for _, kind, data in rows if kind == "edited" and "timed_call" in data
            ] == [
                {
                    "changed": ["call_timing"],
                    "timed_call": dial,
                    "duration_seconds": 45,
                    "device_id": device,
                    "source": "recording",
                }
            ]

    run(exercise())


def test_a_first_call_history_read_only_times_dials_past_a_week(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """The first read after the seller allows the call history goes back 30 days, but a row
    older than a week only fills a dial's outcome: it is never a call of its own."""

    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            lead = await here.add("Alex Example", "+12025550123")
            here.as_seller()
            dialled = await here.client.post(
                f"{BASE}/leads/{lead}/calls/phone",
                json={"command_id": str(uuid4()), "duration_seconds": 90},
                headers=WRITE,
            )
            assert dialled.status_code == 200, dialled.text
            dial = next(e["event_id"] for e in dialled.json()["events"] if e["kind"] == "call")
            now = datetime.now(UTC)
            # The lead and its dial are three weeks old.
            async with here.setup.sessions() as db, db.begin():
                await db.execute(
                    update(Lead)
                    .where(Lead.id == UUID(lead))
                    .values(created_at=now - timedelta(days=25))
                )
                await db.execute(
                    update(LeadEvent)
                    .where(LeadEvent.id == UUID(dial))
                    .values(created_at=now - timedelta(days=21))
                )
            dial_start = now - timedelta(days=21, seconds=90)

            def row(log_id: str, at: datetime, seconds: int) -> dict[str, Any]:
                return {
                    "log_id": log_id,
                    "number": "+12025550123",
                    "started_at": at.isoformat(),
                    "duration_seconds": seconds,
                    "direction": "outgoing",
                }

            calls = [
                # The dial, as the phone's own history has it.
                row("201", dial_start + timedelta(seconds=10), 64),
                # A dialer call 20 days ago with no dial in the app.
                row("202", now - timedelta(days=20), 30),
            ]
            body = {"device_id": str(uuid4()), "calls": calls}
            usual = await here.client.post(f"{BASE}/phone-log", json=body, headers=WRITE)
            assert usual.status_code == 200, usual.text
            assert (usual.json()["logged"], usual.json()["skipped"]) == (0, 2)
            first = await here.client.post(
                f"{BASE}/phone-log", json=body | {"backfill": True}, headers=WRITE
            )
            assert first.status_code == 200, first.text
            assert (first.json()["logged"], first.json()["already"]) == (0, 1)
            assert first.json()["skipped"] == 1

            async with here.setup.sessions() as db:
                rows = (
                    await db.execute(
                        select(LeadEvent.kind, LeadEvent.data).where(
                            LeadEvent.lead_id == UUID(lead)
                        )
                    )
                ).all()
            assert [data.get("via") for kind, data in rows if kind == "call"] == [None]
            assert [
                (data["timed_call"], data["duration_seconds"])
                for kind, data in rows
                if kind == "edited" and "timed_call" in data
            ] == [(dial, 64)]

    run(exercise())
