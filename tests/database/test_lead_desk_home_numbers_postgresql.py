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
from sqlalchemy import Engine, update

from ac_platform.lead_desk.hours import IST
from ac_platform.lead_desk.models import Lead, LeadEvent
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, later, world


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
            # Talk time is the phone's own; the app's dial is time away, an estimate.
            assert week["talk_seconds"] == 120, week
            assert week["talk_estimated_seconds"] == 95, week
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
    the seller's calls, inside the team's work hours from the first call (Persona QA,
    31 Oct 2026: never a night or a day off), from each call's real start and seconds."""

    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            # Work hours all week, the whole day, so the gaps are inside them.
            here.as_admin()
            team = (await here.client.get(f"{BASE}/team")).json()
            hours = await here.client.put(
                f"{BASE}/work-hours",
                json={
                    "expected_revision": team["settings"]["revision"],
                    "days": [0, 1, 2, 3, 4, 5, 6],
                    "start": "00:00",
                    "end": "23:59",
                    "pause_leads": False,
                    "breaks": [],
                },
                headers=WRITE,
            )
            assert hours.status_code == 200, hours.text
            here.as_seller()
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
            # 30 min ago for 2 min, 20 min ago for 1 min, 5 min ago for 30 s: gaps of 8
            # and 14 min, and the four and a half since the last call.
            assert [gap["minutes"] for gap in desk["breaks"]][:2] == [14, 8]
            assert len(desk["breaks"]) == 3
            assert not any(gap["planned"] or gap["approximate"] for gap in desk["breaks"])

    run(exercise())


def test_a_leads_calls_say_connected_as_home_counts_them(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """One rule for connected (Leads session and Home, 1 Nov 2026): a lead's call events say
    connected when Home would count them so (talk seconds the phone measured), keep what was
    saved otherwise, and a Call-button dial's time away is never evidence either way."""

    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            lead = await here.add("Fictional Connected One", "98760 67031")
            now = datetime.now(UTC)
            calls: list[tuple[int, dict[str, Any]]] = [
                # The phone timed it; its log saved no flag.
                (30, {"via": "phone", "direction": "outgoing", "duration_seconds": 30}),
                # The phone's log: not answered.
                (
                    20,
                    {
                        "via": "phone",
                        "direction": "outgoing",
                        "duration_seconds": 0,
                        "connected": False,
                    },
                ),
                # A Call-button dial: 45 s away from the app, nothing else known.
                (10, {"simulated": False, "estimated": True, "duration_seconds": 45}),
            ]
            async with here.setup.sessions() as db, db.begin():
                for minutes, data in calls:
                    db.add(
                        LeadEvent(
                            id=uuid4(),
                            tenant_id=here.tenant_id,
                            lead_id=UUID(lead),
                            kind="call",
                            actor_person_id=here.seller.person_id,
                            data=data,
                            created_at=now - timedelta(minutes=minutes),
                        )
                    )
            detail = await here.client.get(f"{BASE}/leads/{lead}")
            assert detail.status_code == 200, detail.text
            seen = {
                event["duration_seconds"]: event["connected"]
                for event in detail.json()["events"]
                if event["kind"] == "call"
            }
            assert seen == {30: True, 0: False, 45: None}

    run(exercise())


def test_the_same_day_counts_the_same_calls_everywhere(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """Hardcore phone QA ph1-30/31 (1 Nov 2026): Reports, Home and Growth counted the same day
    differently. One rule (_call_rows) feeds each: two calls out (one answered), a call in
    nobody took, and an after-call answer with no call behind it make 2 calls, 1 connected."""

    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            lead = await here.add("Fictional Count One", "98760 67041")
            now = datetime.now(UTC)
            events: list[tuple[str, int, dict[str, Any]]] = [
                (
                    "call",
                    30,
                    {
                        "via": "phone",
                        "direction": "outgoing",
                        "duration_seconds": 40,
                        "connected": True,
                    },
                ),
                (
                    "call",
                    20,
                    {
                        "via": "phone",
                        "direction": "outgoing",
                        "duration_seconds": 0,
                        "connected": False,
                    },
                ),
                (
                    "call",
                    15,
                    {
                        "via": "phone",
                        "direction": "missed",
                        "duration_seconds": 0,
                        "connected": False,
                    },
                ),
                ("result", 10, {"connected": True, "stage": "follow_up", "from_stage": "new"}),
            ]
            async with here.setup.sessions() as db, db.begin():
                for kind, minutes, data in events:
                    db.add(
                        LeadEvent(
                            id=uuid4(),
                            tenant_id=here.tenant_id,
                            lead_id=UUID(lead),
                            kind=kind,
                            actor_person_id=here.seller.person_id,
                            data=data,
                            created_at=now - timedelta(minutes=minutes),
                        )
                    )
            # Just after midnight India time the calls are yesterday's.
            if (now - timedelta(minutes=31)).astimezone(IST).date() != now.astimezone(IST).date():
                return
            desk = (await here.client.get(BASE)).json()
            assert (desk["numbers"]["calls"], desk["numbers"]["connected"]) == (2, 1)
            mine = (await here.client.get(f"{BASE}/performance/sellers?days=1")).json()
            seller = mine["sellers"][0]
            assert seller["inbound"]["attempted"] + seller["cold"]["attempted"] == 2
            here.as_admin()
            report = await here.client.get(f"{BASE}/reports/performance", params={"days": 1})
            assert report.status_code == 200, report.text
            today = report.json()["current"]
            assert (today["calls"], today["connected"]) == (2, 1)

    run(exercise())


def test_each_sellers_row_has_follow_ups_and_the_month(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """Competitor teardown #18 (1 Nov 2026): the Performance table's row for each seller has
    follow-ups done as Home counts them (a call out to a lead past New) and wins in rupees, and
    the engine reads this month so far."""

    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            lead = await here.add("Fictional Table One", "98760 67051")
            now = datetime.now(UTC)
            events: list[tuple[str, int, dict[str, Any]]] = [
                ("stage", 60, {"stage": "follow_up", "from_stage": "new"}),
                (
                    "call",
                    30,
                    {
                        "via": "phone",
                        "direction": "outgoing",
                        "duration_seconds": 40,
                        "connected": True,
                    },
                ),
            ]
            async with here.setup.sessions() as db, db.begin():
                for kind, minutes, data in events:
                    db.add(
                        LeadEvent(
                            id=uuid4(),
                            tenant_id=here.tenant_id,
                            lead_id=UUID(lead),
                            kind=kind,
                            actor_person_id=here.seller.person_id,
                            data=data,
                            created_at=now - timedelta(minutes=minutes),
                        )
                    )
            # Just after midnight India time the move and the call are yesterday's.
            if (now - timedelta(minutes=61)).astimezone(IST).date() != now.astimezone(IST).date():
                return
            today = await here.client.get(f"{BASE}/performance/sellers?days=1")
            assert today.status_code == 200, today.text
            row = today.json()["sellers"][0]
            assert (row["follow_ups_done"], row["won_amount"]) == (1, 0)
            month = await here.client.get(
                f"{BASE}/performance/sellers", params={"days": "1", "month": "true"}
            )
            assert month.status_code == 200, month.text
            assert month.json()["days"] == now.astimezone(IST).day
            assert month.json()["sellers"][0]["follow_ups_done"] == 1

    run(exercise())


def test_the_desk_carries_inbound_and_cold_apart(postgres_harness: Any, tmp_path: Path) -> None:
    """Dipak's Home + Leads handoff (31 Oct 2026): the desk carries each side of my day, so
    Home's Inbound | Cold selector switches with no second read. A lead's side is its
    pipeline (migration 0146: "cold" is Cold, the rest Inbound); each side's cards count
    exactly the Leads lists they open."""

    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            hot = await here.add("Fictional Side Inbound", "98760 67041")
            cold = await here.add("Fictional Side Cold", "98760 67042")
            await here.add("Fictional Side Cold Two", "98760 67043")
            async with here.setup.sessions() as db, db.begin():
                await db.execute(
                    update(Lead)
                    .where(Lead.name.like("Fictional Side Cold%"))
                    .values(pipeline="cold")
                )
                stored = await here.stored(hot)
                # The Inbound call the phone timed (connected); a dial with no talk on Cold
                # (a dial's time away alone never connects: phone personas, 1 Nov 2026).
                timed = {"via": "phone", "direction": "outgoing", "duration_seconds": 60}
                for lead_id, data in ((hot, timed), (cold, {"duration_seconds": 0})):
                    db.add(
                        LeadEvent(
                            id=uuid4(),
                            tenant_id=here.tenant_id,
                            lead_id=UUID(lead_id),
                            kind="call",
                            actor_person_id=here.seller.person_id,
                            data={**data, "simulated": False},
                            created_at=stored.created_at,
                        )
                    )
            desk = (await here.client.get(f"{BASE}")).json()
            inbound, cool = desk["sides"]["inbound"], desk["sides"]["cold"]
            # To Call in the first stage: the side's new leads never called.
            assert (inbound["counts"]["new"], cool["counts"]["new"]) == (1, 2)
            assert inbound["counts"]["open_leads"] == cool["counts"]["open_leads"] == 0
            assert inbound["counts"]["follow_ups_today"] == 0
            assert inbound["new_key"] == "new"
            # Each side's calls only; the whole day's numbers keep both.
            assert (inbound["numbers"]["calls"], inbound["numbers"]["connected"]) == (1, 1)
            assert (cool["numbers"]["calls"], cool["numbers"]["connected"]) == (1, 0)
            assert desk["numbers"]["calls"] == 2
            # The next lead on each side; new Cold leads oldest first.
            assert inbound["next_lead"]["lead_id"] == hot
            assert cool["next_lead"]["lead_id"] == cold
            assert inbound["upcoming"] == cool["upcoming"] == []
            # The countdown: an untouched Cold list is never "to call today".
            assert inbound["to_call_today"]["called"] == 1
            assert cool["to_call_today"] == {"left": 0, "called": 1}

    run(exercise())


def test_the_next_lead_who_rang_says_so(postgres_harness: Any, tmp_path: Path) -> None:
    """Leads 2 (1 Nov 2026): a missed call not yet returned is To Call's first row, so Home's
    next lead can be one; its row says when they rang and how often, as on Leads."""

    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            await here.add("Fictional Waiting First", "98760 67051")
            rang = await here.add("Fictional Rang Twice", "98760 67052")
            desk = (await here.client.get(f"{BASE}")).json()
            # Nobody has rung yet: the next lead says nothing of a missed call.
            assert desk["sides"]["inbound"]["next_lead"]["missed_at"] is None, desk["sides"]
            now = datetime.now(UTC)
            async with here.setup.sessions() as db, db.begin():
                for minutes in (20, 10):
                    db.add(
                        LeadEvent(
                            id=uuid4(),
                            tenant_id=here.tenant_id,
                            lead_id=UUID(rang),
                            kind="call",
                            actor_person_id=here.seller.person_id,
                            data={
                                "via": "phone",
                                "direction": "missed",
                                "duration_seconds": 0,
                                "connected": False,
                            },
                            created_at=now - timedelta(minutes=minutes),
                        )
                    )
            first = (await here.client.get(f"{BASE}")).json()["sides"]["inbound"]["next_lead"]
            assert first["lead_id"] == rang, first
            assert first["missed_calls"] == 2 and first["missed_at"] is not None, first

    run(exercise())
