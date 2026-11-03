"""Once a lead was reached it never falls back to Not Connected, through the Sales Xray CRM's
HTTP API on PostgreSQL (Dipak's model, orchestrator, 3 Nov 2026, bug 134: Open Leads means
some discussion happened, Not Connected means never reached). A New lead the phone shows was
answered, with no outcome logged, goes to Open Leads at its next unanswered call, never to
Not Connected; later unanswered calls leave its stage alone and only move its retry; a lead
nobody ever reached still goes to Not Connected. The phone's own log never moves the lead
by itself: it arrives before the seller's answer, which may be Junk or Call back."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine

from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_a_reached_lead_never_falls_back_to_not_connected(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            never = await here.add("Fictional Never Reached", "98761 10001")
            talked = await here.add("Fictional Talked Once", "98761 10002")
            earned = await here.add("Fictional Interested", "98761 10003")
            here.as_seller()

            async def dispose(lead_id: str, **body: Any) -> dict[str, Any]:
                detail = await here.detail(lead_id)
                answer = await here.client.post(
                    f"{BASE}/leads/{lead_id}/dispose",
                    json={
                        "command_id": str(uuid4()),
                        "expected_revision": detail["lead"]["revision"],
                        **body,
                    },
                    headers=WRITE,
                )
                assert answer.status_code == 200, answer.text
                return dict(answer.json()["lead"])

            # Nobody ever reached it: an unanswered call makes it Not Connected.
            first = await dispose(never, connected=False, reason="did_not_pick")
            assert first["stage"] == "not_connected"

            # The phone shows a 95-second call on a New lead, and no outcome was logged.
            logged = await here.client.post(
                f"{BASE}/phone-log",
                json={
                    "device_id": str(uuid4()),
                    "calls": [
                        {
                            "log_id": "201",
                            "number": "9876110002",
                            "started_at": (datetime.now(UTC) - timedelta(minutes=3)).isoformat(),
                            "duration_seconds": 95,
                            "direction": "outgoing",
                        }
                    ],
                },
                headers=WRITE,
            )
            assert logged.status_code == 200, logged.text
            assert logged.json()["logged"] == 1
            # The log alone moves nothing: the seller's own answer comes next.
            assert (await here.detail(talked))["lead"]["stage"] == "new"
            # Unanswered next time: Open Leads, never Not Connected.
            again = await dispose(talked, connected=False, reason="did_not_pick")
            assert again["stage"] == "follow_up"
            assert again["next_action_at"] is not None
            # Unanswered again: its stage stays; only its retry moves.
            third = await dispose(talked, connected=False, reason="did_not_pick")
            assert third["stage"] == "follow_up"

            # Connected and moved on ("We talked", Interested), then unanswered: it stays.
            moved = await dispose(
                earned,
                connected=True,
                stage="interested",
                follow_up_at=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
            )
            assert moved["stage"] == "interested"
            later = await dispose(earned, connected=False, reason="did_not_pick")
            assert later["stage"] == "interested"

    run(exercise())
