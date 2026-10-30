"""Home's zero states on PostgreSQL (owner, 25 Oct 2026: "show the next useful data, the
last days or weeks", and a member with no leads saw "No leads yet" while hundreds waited):
the desk carries yesterday's and the last seven days' numbers beside today's, and the
workspace's open and unassigned leads with whether this person takes new ones."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine

from ac_platform.lead_desk.hours import IST
from ac_platform.lead_desk.models import LeadEvent
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, later, world


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_yesterday_the_week_and_the_team_pool(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            first = await here.add("Fictional Home One", "98760 67001")
            await here.add("Fictional Home Two", "98760 67002")
            talked = await here.dispose(
                first, connected=True, step="interested", follow_up_at=later(days=1)
            )
            assert talked.status_code == 200, talked.text
            # Home counts the calls Recent Calls lists (owner, 30 Oct 2026): today
            # the seller called from the app; yesterday too, to a lead past New then.
            async with here.setup.sessions() as db, db.begin():
                stored = await here.stored(first)
                yesterday = stored.created_at - timedelta(days=1)
                for kind, at, data in (
                    ("stage", yesterday - timedelta(hours=1), {"stage": "follow_up"}),
                    ("call", yesterday, {"duration_seconds": 40, "simulated": False}),
                    ("call", stored.created_at, {"duration_seconds": 25, "simulated": False}),
                ):
                    db.add(
                        LeadEvent(
                            id=uuid4(),
                            tenant_id=here.tenant_id,
                            lead_id=UUID(first),
                            kind=kind,
                            actor_person_id=here.seller.person_id,
                            data=data,
                            created_at=at,
                        )
                    )
            desk = (await here.client.get(f"{BASE}")).json()
            assert desk["numbers"]["calls"] == 1 and desk["numbers"]["connected"] == 1
            assert desk["numbers_yesterday"]["calls"] == 1
            assert desk["numbers_yesterday"]["follow_ups_done"] == 1
            assert desk["numbers_week"]["calls"] == 2
            assert desk["team_pool"] == {"open": 2, "unassigned": 0, "may_take": True}
            # The admin has no leads of their own and takes none: the pool says what's there.
            here.as_admin()
            theirs = (await here.client.get(f"{BASE}")).json()
            assert theirs["numbers"]["calls"] == 0
            assert theirs["team_pool"] == {"open": 2, "unassigned": 0, "may_take": False}

    run(exercise())


def test_numbers_count_the_calls_recent_calls_lists(postgres_harness: Any, tmp_path: Path) -> None:
    """Owner, 30 Oct 2026: Analyse yourself said 0 beside a list of calls, because a
    call placed in the app never counted. Every call out counts, from the stored
    calls, on read: attempted, connected (talk above 0), not connected, talk time,
    and follow-ups done (a call to a lead past New then). An outcome is not a call;
    a call in or a missed call is not a call out."""

    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            first = await here.add("Fictional Numbers One", "98760 67011")
            second = await here.add("Fictional Numbers Two", "98760 67012")
            async with here.setup.sessions() as db, db.begin():
                stored = await here.stored(first)
                base = stored.created_at - timedelta(days=1)

                def event(lead: str, kind: str, minutes: int, data: dict[str, Any]) -> None:
                    db.add(
                        LeadEvent(
                            id=uuid4(),
                            tenant_id=here.tenant_id,
                            lead_id=UUID(lead),
                            kind=kind,
                            actor_person_id=here.seller.person_id,
                            data=data,
                            created_at=base + timedelta(minutes=minutes),
                        )
                    )

                # The second lead was past New before these calls.
                event(second, "stage", -60, {"stage": "follow_up", "from_stage": "new"})
                # A call placed in the app to a New lead, 95 s; its outcome is not
                # another call.
                event(
                    first,
                    "call",
                    5,
                    {
                        "submission_id": None,
                        "simulated": False,
                        "duration_seconds": 95,
                        "sample": None,
                    },
                )
                event(
                    first,
                    "result",
                    8,
                    {
                        "connected": True,
                        "stage": "follow_up",
                        "from_stage": "new",
                        "was_due": False,
                    },
                )
                # The phone's log: a call out nobody answered, a call in, a missed call.
                event(
                    second,
                    "call",
                    10,
                    {
                        "via": "phone",
                        "direction": "outgoing",
                        "duration_seconds": 0,
                        "connected": False,
                    },
                )
                event(
                    second,
                    "call",
                    11,
                    {
                        "via": "phone",
                        "direction": "incoming",
                        "duration_seconds": 60,
                        "connected": True,
                    },
                )
                event(
                    second,
                    "call",
                    12,
                    {
                        "via": "phone",
                        "direction": "missed",
                        "duration_seconds": 0,
                        "connected": False,
                    },
                )
                # A recorded call, 120 s.
                event(
                    second,
                    "call",
                    14,
                    {"via": "dialler_recording", "duration_seconds": 120, "connected": True},
                )
            desk = (await here.client.get(f"{BASE}")).json()
            week = desk["numbers_week"]
            assert week["calls"] == 3, week
            assert week["connected"] == 2 and week["not_connected"] == 1, week
            assert week["talk_seconds"] == 95 + 120, week
            assert week["follow_ups_done"] == 2, week
            # Another person's numbers never count these calls.
            here.as_admin()
            theirs = (await here.client.get(f"{BASE}")).json()["numbers_week"]
            assert theirs["calls"] == 0 and theirs["talk_seconds"] == 0

    run(exercise())


def test_today_counts_down_and_ends_with_the_longest_breaks(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """Leads redesign section 6 (owner and Dipak, 30 Oct 2026): today's work counts down
    as calls happen (20 -> 19 -> 18), and Home ends with the three longest gaps between
    the seller's calls: with no work hours set, from the first call to the last, from
    each call's real start and seconds."""

    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            first = await here.add("Fictional Break One", "98760 67021")
            await here.add("Fictional Break Two", "98760 67022")
            before = (await here.client.get(f"{BASE}")).json()
            assert before["to_call_today"] == {"left": 2, "called": 0}
            assert before["breaks"] == []
            now = datetime.now(UTC)
            async with here.setup.sessions() as db, db.begin():
                for minutes, seconds in ((30, 120), (20, 60), (5, 30)):
                    db.add(
                        LeadEvent(
                            id=uuid4(),
                            tenant_id=here.tenant_id,
                            lead_id=UUID(first),
                            kind="call",
                            actor_person_id=here.seller.person_id,
                            data={
                                "via": "phone",
                                "direction": "outgoing",
                                "duration_seconds": seconds,
                                "connected": True,
                            },
                            created_at=now - timedelta(minutes=minutes),
                        )
                    )
            desk = (await here.client.get(f"{BASE}")).json()
            # Just after midnight India time the earlier calls are yesterday's.
            if (now - timedelta(minutes=31)).astimezone(IST).date() != now.astimezone(IST).date():
                return
            assert desk["to_call_today"] == {"left": 1, "called": 1}
            # 30 min ago for 2 min, 20 min ago for 1 min, 5 min ago: gaps of 8 and 14 min.
            assert [gap["minutes"] for gap in desk["breaks"]] == [14, 8]
            assert not any(gap["planned"] or gap["approximate"] for gap in desk["breaks"])

    run(exercise())
