"""The sales team's 15 acceptance tests for the lead pipeline (Lead OS, 24 Oct 2026), on
PostgreSQL through the Sales X-Ray CRM's HTTP API.

The organisation picks the generic nine-stage template ("Inside sales with demos"); a
seller works fictional leads through it. Every test checks the spec's principle: one
lead record, one current stage, many possible moves, the whole history, no duplicates.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import Engine, func, select, update

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.http import install_lead_desk_http
from ac_platform.lead_desk.journey.http import install_journey_http
from ac_platform.lead_desk.models import Lead, LeadEvent, LeadMeeting
from ac_platform.lead_desk.store import LeadDesk, Viewer
from ac_platform.tenancy.models import Membership, Organisation
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup

ROOT = Path(__file__).resolve().parents[2]
WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
BASE = "/v1/lead-desk"


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def later(**delta: float) -> str:
    return (datetime.now(UTC) + timedelta(**delta)).isoformat()


@dataclass
class World:
    setup: Any
    client: httpx.AsyncClient
    seller: Any
    seller_token: str

    def as_admin(self) -> None:
        self.client.cookies.set(self.setup.settings.session_cookie_name, self.setup.token)

    def as_seller(self) -> None:
        self.client.cookies.set(self.setup.settings.session_cookie_name, self.seller_token)

    @property
    def tenant_id(self) -> UUID:
        return UUID(str(self.setup.state.tenant_id))

    async def add(self, name: str, phone: str) -> str:
        self.as_admin()
        added = await self.client.post(
            f"{BASE}/leads",
            json={"command_id": str(uuid4()), "name": name, "phone": phone},
            headers=WRITE,
        )
        assert added.status_code == 201, added.text
        self.as_seller()
        return str(added.json()["lead"]["lead_id"])

    async def detail(self, lead_id: str) -> dict[str, Any]:
        found = await self.client.get(f"{BASE}/leads/{lead_id}")
        assert found.status_code == 200, found.text
        body: dict[str, Any] = found.json()
        return body

    async def move(self, lead_id: str, step: str, **extra: Any) -> httpx.Response:
        revision = (await self.detail(lead_id))["lead"]["revision"]
        return await self.client.post(
            f"{BASE}/leads/{lead_id}/stage",
            json={
                "commandId": str(uuid4()),
                "expectedRevision": revision,
                "step": step,
                "via": "board",
                **extra,
            },
            headers=WRITE,
        )

    async def dispose(self, lead_id: str, **body: Any) -> httpx.Response:
        revision = (await self.detail(lead_id))["lead"]["revision"]
        return await self.client.post(
            f"{BASE}/leads/{lead_id}/dispose",
            json={"command_id": str(uuid4()), "expected_revision": revision, **body},
            headers=WRITE,
        )

    async def post(self, path: str, lead_id: str, **body: Any) -> httpx.Response:
        revision = (await self.detail(lead_id))["lead"]["revision"]
        return await self.client.post(
            f"{BASE}{path}",
            json={"command_id": str(uuid4()), "expected_revision": revision, **body},
            headers=WRITE,
        )

    async def leads(self) -> int:
        async with self.setup.sessions() as db:
            return int(
                await db.scalar(select(func.count()).where(Lead.tenant_id == self.tenant_id)) or 0
            )

    async def events(self, lead_id: str) -> list[LeadEvent]:
        async with self.setup.sessions() as db:
            return list(
                (
                    await db.scalars(
                        select(LeadEvent)
                        .where(LeadEvent.lead_id == UUID(lead_id))
                        .order_by(LeadEvent.created_at)
                    )
                ).all()
            )

    async def stored(self, lead_id: str) -> Lead:
        async with self.setup.sessions() as db:
            lead = await db.scalar(select(Lead).where(Lead.id == UUID(lead_id)))
            assert lead is not None
            return lead


@asynccontextmanager
async def world(postgres_harness: Any, tmp_path: Path) -> AsyncIterator[World]:
    setup = await _setup(postgres_harness, tmp_path)
    try:
        async with setup.sessions() as db, db.begin():
            db.add(
                Organisation(
                    tenant_id=setup.state.tenant_id,
                    created_by_person_id=setup.state.person_id,
                    creation_command_id=uuid4(),
                    domain_verification_token=uuid4().hex + uuid4().hex,
                )
            )
            await db.execute(
                update(Membership)
                .where(Membership.person_id == setup.state.person_id)
                .values(role="admin")
            )
        settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
        context = RouteContext(settings, setup.require_actor, setup.sessions)
        install_lead_desk_http(setup.app, context)
        install_journey_http(setup.app, context)
        seller = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
        seller_token = await _session(setup, seller)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
        ) as client:
            here = World(setup, client, seller, seller_token)
            here.as_admin()
            picked = await client.post(
                f"{BASE}/journey/template",
                json={"expectedVersion": 0, "template": "inside_sales_demos"},
                headers=WRITE,
            )
            assert picked.status_code == 200, picked.text
            # New leads go to the seller.
            for person, available in ((seller.person_id, True), (setup.state.person_id, False)):
                saved = await client.put(
                    f"{BASE}/team/{person}",
                    json={"expected_revision": 0, "available": available, "max_open": 50},
                    headers=WRITE,
                )
                assert saved.status_code == 200, saved.text
            here.as_seller()
            yield here
    finally:
        await setup.engine.dispose()


def digest(events: list[LeadEvent]) -> dict[UUID, str]:
    return {
        event.id: hashlib.sha256(
            json.dumps(
                [event.kind, event.data, event.created_at.isoformat()], sort_keys=True, default=str
            ).encode()
        ).hexdigest()
        for event in events
    }


# ----- 1. A new inquiry creates one record in New -----------------------------------------


def test_at01_a_new_inquiry_creates_one_record_in_new(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            admin = here.setup.state.person_id
            async with here.setup.sessions() as db, db.begin():
                desk = LeadDesk(
                    db, Viewer(person_id=admin, tenant_id=here.tenant_id, role="admin", name="A")
                )
                outcomes = []
                for phone, source in (
                    ("+91 98765 43210", "webhook"),
                    ("098765 43210", "meta"),
                    ("919876543210", "webhook"),
                ):
                    lead, outcome = await desk.ingest(
                        {"name": "Fictional Asha", "phone": phone}, source=source
                    )
                    assert lead is not None
                    outcomes.append((lead.id, outcome))
            assert [outcome for _, outcome in outcomes] == ["created", "repeat", "repeat"]
            assert len({lead_id for lead_id, _ in outcomes}) == 1
            assert await here.leads() == 1
            lead_id = str(outcomes[0][0])
            kinds = [event.kind for event in await here.events(lead_id)]
            assert kinds.count("captured") == 1 and kinds.count("repeat") == 2
            here.as_admin()
            row = (await here.detail(lead_id))["lead"]
            assert (row["stage"], row["step"], row["stage_label"]) == ("new", "new", "New lead")
            board = (await here.client.get(f"{BASE}/board")).json()
            new = board["groups"][0]["columns"][0]
            assert new["step"] == "new" and [c["lead_id"] for c in new["cards"]] == [lead_id]

    run(exercise())


# ----- 2-7, 13-15: one lead through the whole pipeline ------------------------------------


def test_at02_to_at07_one_lead_moves_through_every_stage_on_the_same_record(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            lead_id = await here.add("Fictional Ravi", "98765 11111")
            assert await here.leads() == 1

            # 2. An unanswered call: the same record moves to Not Connected.
            missed = await here.dispose(lead_id, connected=False, reason="did_not_pick")
            assert missed.status_code == 200, missed.text
            row = missed.json()["lead"]
            assert row["lead_id"] == lead_id
            assert (row["stage"], row["step"]) == ("not_connected", "not_connected")
            assert row["next_action_at"] is not None  # the retry rule's next try

            # 3. They answer and are interested: a follow-up is needed (422 without one).
            refused = await here.dispose(lead_id, connected=True, step="interested")
            assert refused.status_code == 422
            interested = await here.dispose(
                lead_id, connected=True, step="interested", follow_up_at=later(days=1)
            )
            assert interested.status_code == 200, interested.text
            assert interested.json()["lead"]["step"] == "interested"

            # 4. The discussion is interrupted: Discussion Incomplete, with when to resume.
            needs = await here.move(lead_id, "discussion_incomplete")
            assert needs.status_code == 422 and "follow up" in needs.json()["detail"]
            moved = await here.move(lead_id, "discussion_incomplete", nextActionAt=later(hours=6))
            assert moved.status_code == 200, moved.text
            assert moved.json()["stepLabel"] == "Discussion incomplete"

            # 5. A meeting is booked: Meeting / Demo Scheduled, with its date, type, link.
            assert (await here.move(lead_id, "meeting_scheduled")).status_code == 422
            booked = await here.move(
                lead_id,
                "meeting_scheduled",
                meeting={
                    "startsAt": later(days=2),
                    "mode": "zoom",
                    "link": "https://zoom.us/j/1234567890",
                },
            )
            assert booked.status_code == 200, booked.text
            meeting_id = booked.json()["meetingId"]
            assert meeting_id is not None
            # Postponed: the same meeting moves; its history keeps both times.
            moved_meeting = await here.post(
                f"/leads/{lead_id}/meetings",
                lead_id,
                meeting={"starts_at": later(days=3), "mode": "google_meet"},
            )
            assert moved_meeting.status_code == 200, moved_meeting.text
            meeting = moved_meeting.json()["meeting"]
            assert meeting["meeting_id"] == meeting_id and meeting["revision"] == 2
            assert meeting["mode_label"] == "Google Meet"
            async with here.setup.sessions() as db:
                rows = (
                    await db.scalars(
                        select(LeadMeeting).where(LeadMeeting.lead_id == UUID(lead_id))
                    )
                ).all()
            assert len(rows) == 1
            actions = [e.data["action"] for e in await here.events(lead_id) if e.kind == "meeting"]
            assert actions == ["scheduled", "rescheduled"]

            # 6. The meeting happens: Demo / Zoom Meeting Completed.
            done = await here.post(
                f"/meetings/{meeting_id}/done",
                lead_id,
                note="Showed the plan; they will discuss at home",
                next_action_at=later(days=4),
            )
            assert done.status_code == 200, done.text
            body = done.json()
            assert body["lead"]["step"] == "demo_completed" and body["meeting"] is None

            # 14. Under consideration: it stays in Demo Completed with a new follow-up.
            stages_before = [e.id for e in await here.events(lead_id) if e.kind == "stage"]
            follow = await here.post(f"/leads/{lead_id}/follow-up", lead_id, at=later(days=5))
            assert follow.status_code == 200, follow.text
            assert follow.json()["lead"]["step"] == "demo_completed"
            assert [e.id for e in await here.events(lead_id) if e.kind == "stage"] == (
                stages_before
            )

            # 7. The deal closes: Closed / Won, out of the follow-ups.
            won = await here.move(lead_id, "won")
            assert won.status_code == 200, won.text
            row = (await here.detail(lead_id))["lead"]
            assert (row["step"], row["group"], row["next_action_at"]) == ("won", "won", None)

            # 11. Not one move made a second record.
            assert await here.leads() == 1

            # 13. The history shows every move, in order, with who and how.
            here.as_admin()
            events = (await here.detail(lead_id))["events"]
            moves = [e for e in reversed(events) if e["action"] in ("move", "close", "reopen")]
            assert [(e["from_label"], e["stage_label"]) for e in moves] == [
                ("New lead", "Not connected"),
                ("Not connected", "Interested"),
                ("Interested", "Discussion incomplete"),
                ("Discussion incomplete", "Meeting/Demo scheduled"),
                ("Meeting/Demo scheduled", "Meeting/Demo completed"),
                ("Meeting/Demo completed", "Won"),
            ]
            assert all(e["actor_name"] and e["move_source"] == "seller" for e in moves)

            # 15. Reopening Won is a manager's; it comes back where it was closed from.
            before = digest(await here.events(lead_id))
            here.as_seller()
            refused = await here.post(
                f"/leads/{lead_id}/reopen", lead_id, next_action_at=later(days=1)
            )
            assert refused.status_code == 403
            here.as_admin()
            reopened = await here.post(
                f"/leads/{lead_id}/reopen", lead_id, next_action_at=later(days=1)
            )
            assert reopened.status_code == 200, reopened.text
            assert reopened.json()["lead"]["step"] == "demo_completed"
            # Reassigned to the admin: history kept too.
            assigned = await here.post(
                f"/leads/{lead_id}/assign", lead_id, person_id=str(here.setup.state.person_id)
            )
            assert assigned.status_code == 200, assigned.text
            after = digest(await here.events(lead_id))
            assert {k: v for k, v in after.items() if k in before} == before
            kinds = [e.kind for e in await here.events(lead_id)]
            assert kinds[-2:] == ["stage", "reassigned"]
            assert await here.leads() == 1

    run(exercise())


# ----- 8. Declines → Lost, with a reason -------------------------------------------------


def test_at08_a_lead_who_declines_is_lost_with_a_reason(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            lead_id = await here.add("Fictional Meera", "98765 22222")
            assert (await here.move(lead_id, "lost")).status_code == 422
            other = await here.move(lead_id, "lost", reason="other")
            assert other.status_code == 422 and "Other" in other.json()["detail"]
            assert (await here.move(lead_id, "lost", reason="fake")).status_code == 422
            lost = await here.move(lead_id, "lost", reason="price")
            assert lost.status_code == 200, lost.text
            row = (await here.detail(lead_id))["lead"]
            assert (row["stage"], row["outcome_reason"], row["outcome_reason_label"]) == (
                "lost",
                "price",
                "Price or budget",
            )
            # The seller reopens it when they come back; the reason clears.
            reopened = await here.post(
                f"/leads/{lead_id}/reopen",
                lead_id,
                step="interested",
                next_action_at=later(days=1),
            )
            assert reopened.status_code == 200, reopened.text
            stored = await here.stored(lead_id)
            assert (stored.stage, stored.outcome_reason) == ("interested", None)
            assert await here.leads() == 1

    run(exercise())


# ----- 9. Fake → Lost, not a real lead, apart from a lost deal ------------------------------


def test_at09_a_fake_lead_is_lost_as_not_a_real_lead_apart_from_a_lost_deal(
    postgres_harness: Any, tmp_path: Path
) -> None:
    # The sales team's eight stages (owner, 25 Oct 2026) keep Junk in Lost: a fake lead
    # is Lost, "Junk / not a real lead", and never counts as a lost deal.
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            junk = await here.add("Fictional Spam", "98765 33333")
            lost = await here.add("Fictional Kiran", "98765 44444")
            assert (await here.move(junk, "junk", reason="fake")).status_code == 422
            assert (await here.move(junk, "lost")).status_code == 422
            marked = await here.move(junk, "lost", reason="not_a_lead")
            assert marked.status_code == 200, marked.text
            closed = await here.move(lost, "lost", reason="not_interested")
            assert closed.status_code == 200, closed.text
            row = (await here.detail(junk))["lead"]
            assert (row["stage"], row["group"], row["outcome_reason_label"]) == (
                "lost",
                "lost",
                "Junk / not a real lead",
            )
            # The board has no Junk group: both sit in Lost, each lead once.
            here.as_admin()
            board = (await here.client.get(f"{BASE}/board")).json()
            groups = {group["group"]: group for group in board["groups"]}
            assert "junk" not in groups
            cards = [c["lead_id"] for c in groups["lost"]["columns"][0]["cards"]]
            assert sorted(cards) == sorted([junk, lost])
            assert groups["active"]["count"] == 0

    run(exercise())


# ----- 10. Unanswered calls never make a lead Junk -----------------------------------------


def test_at10_a_lead_who_never_answers_is_not_made_junk(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            lead_id = await here.add("Fictional Sunil", "98765 55555")
            for reason in (
                "did_not_pick",
                "busy",
                "switched_off",
                "did_not_pick",
                "invalid_number",
                "not_in_use",
            ):
                called = await here.dispose(lead_id, connected=False, reason=reason)
                assert called.status_code == 200, called.text
            stored = await here.stored(lead_id)
            assert (stored.stage, stored.attempts, stored.outcome_reason) == (
                "not_connected",
                6,
                None,
            )
            events = await here.events(lead_id)
            assert not any(e.data.get("stage") == "junk" for e in events)
            # One move (New → Not Connected); the other calls are logged, not moves.
            assert sum(1 for e in events if e.data.get("v") == 2) == 1

    run(exercise())


# ----- 11, 12. No duplicates; exactly one current stage ------------------------------------


def test_at11_at12_moves_never_duplicate_and_each_lead_is_in_one_column(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            ids = [await here.add(f"Fictional Lead {n}", f"98765 6666{n}") for n in range(5)]
            assert (await here.move(ids[1], "interested", nextActionAt=later(days=1))).is_success
            assert (await here.move(ids[2], "not_connected", ncReason="busy")).is_success
            assert (await here.move(ids[3], "lost", reason="chose_other")).is_success
            assert (await here.move(ids[4], "lost", reason="not_a_lead")).is_success
            # The same number again attaches to its lead, never a second record.
            again = await here.client.post(
                f"{BASE}/leads",
                json={
                    "command_id": str(uuid4()),
                    "name": "Fictional Lead 1",
                    "phone": "9876566661",
                },
                headers=WRITE,
            )
            assert again.status_code == 201 and again.json()["lead"]["lead_id"] == ids[1]
            assert await here.leads() == 5
            here.as_admin()
            board = (await here.client.get(f"{BASE}/board")).json()
            seen: list[str] = []
            for group in board["groups"]:
                for column in group["columns"]:
                    seen += [card["lead_id"] for card in column["cards"]]
            assert sorted(seen) == sorted(ids) and len(seen) == len(set(seen))
            counts = sum(c["count"] for g in board["groups"] for c in g["columns"])
            assert counts == board["total"] == 5
            # A move the stage list doesn't have is refused with where it can go.
            refused = await here.move(ids[1], "won")
            assert refused.status_code == 409 and "Meeting/Demo scheduled" in refused.text

    run(exercise())


# ----- meetings that don't happen -----------------------------------------------------------


def test_a_missed_meeting_asks_where_the_lead_stands_now(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            lead_id = await here.add("Fictional Divya", "98765 77777")
            plain = {"startsAt": later(days=1), "mode": "in_person", "location": "Fictional office"}
            insecure = await here.move(
                lead_id,
                "meeting_scheduled",
                meeting={**plain, "mode": "zoom", "link": "http://zoom.us/j/1"},
            )
            assert insecure.status_code == 422 and "https://" in insecure.json()["detail"]
            booked = await here.move(lead_id, "meeting_scheduled", meeting=plain)
            assert booked.status_code == 200, booked.text
            meeting_id = booked.json()["meetingId"]
            # Missed: only stages the spec allows from Meeting Scheduled.
            wrong = await here.post(
                f"/meetings/{meeting_id}/not-held", lead_id, status="missed", step="won"
            )
            assert wrong.status_code == 409
            missed = await here.post(
                f"/meetings/{meeting_id}/not-held",
                lead_id,
                status="missed",
                step="not_connected",
                nc_reason="did_not_pick",
            )
            assert missed.status_code == 200, missed.text
            body = missed.json()
            assert body["lead"]["step"] == "not_connected" and body["meeting"] is None
            assert body["lead"]["next_action_at"] is not None
            async with here.setup.sessions() as db:
                row = await db.get(LeadMeeting, UUID(meeting_id))
            assert row is not None and row.status == "missed" and row.closed_at is not None
            # Booked again, then called off by moving the lead on: the meeting closes too.
            again = await here.move(lead_id, "meeting_scheduled", meeting=plain)
            assert again.status_code == 200, again.text
            assert again.json()["meetingId"] != meeting_id
            lost = await here.move(lead_id, "lost", reason="decided_not_to_proceed")
            assert lost.status_code == 200, lost.text
            async with here.setup.sessions() as db:
                statuses = sorted(
                    (
                        await db.scalars(
                            select(LeadMeeting.status).where(LeadMeeting.lead_id == UUID(lead_id))
                        )
                    ).all()
                )
            assert statuses == ["cancelled", "missed"]
            assert await here.leads() == 1

    run(exercise())
