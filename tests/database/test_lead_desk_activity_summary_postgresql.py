"""Owner bug #81: one aggregate, calendar boundaries and the feed's access fences."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine
from sqlalchemy import event as sql_event

from ac_platform.lead_desk.activity_summary import summarize
from ac_platform.lead_desk.errors import DeskError
from ac_platform.lead_desk.models import LeadEvent
from ac_platform.lead_desk.store import PRIVATE_CALL, LeadDesk, Viewer
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, world

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_summary_counts_boundaries_and_actor_not_lead_owner(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            lead = UUID(await here.add("Fictional Summary", "98760 81001"))
            actor = here.seller.person_id
            current_start = datetime(2026, 9, 28, 18, 30, tzinfo=UTC)
            prior_start = datetime(2026, 8, 29, 18, 30, tzinfo=UTC)
            async with here.setup.sessions() as db, db.begin():

                def event(kind: str, at: datetime = NOW, **data: Any) -> None:
                    db.add(
                        LeadEvent(
                            id=uuid4(),
                            tenant_id=here.tenant_id,
                            lead_id=lead,
                            kind=kind,
                            actor_person_id=actor,
                            data=data,
                            created_at=at,
                        )
                    )

                event("call", connected=True)
                event("call", duration_seconds=23)
                event("call", connected=False)
                event("note", current_start)
                event("note", current_start - timedelta(microseconds=1))
                event("stage", prior_start)
                event("stage", prior_start - timedelta(microseconds=1))
                event("call", NOW + timedelta(microseconds=1))
                event("message")
                event("meeting")
                event("result")
                event("captured")
                event("stage", source="template")
                await db.flush()
                desk = LeadDesk(
                    db,
                    Viewer(here.setup.state.person_id, here.tenant_id, "admin", "Fictional Admin"),
                    now=NOW,
                )
                queries: list[str] = []

                def record(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
                    queries.append(statement)

                sql_event.listen(here.setup.engine.sync_engine, "before_cursor_execute", record)
                try:
                    summary = await summarize(desk, team=True)
                finally:
                    sql_event.remove(here.setup.engine.sync_engine, "before_cursor_execute", record)
                assert len(queries) == 2  # One grouped event read and one people directory read.
                assert sum("GROUP BY" in query for query in queries) == 1
                assert summary.current.model_dump() == dict(
                    calls=3, conversations=2, notes=1, moves=0, work=7
                )
                assert summary.previous.model_dump() == dict(
                    calls=0, conversations=0, notes=1, moves=1, work=2
                )
                seller = next(p for p in summary.people if p.id == actor)
                assert seller.current == summary.current
                assert seller.daily[30].notes == 1
                assert seller.daily[29].notes == 1
                assert seller.daily[0].moves == 1
                assert seller.daily[-1].calls == 3
                assert len(seller.daily) == 60
                # Admin's totals stay zero even though they created/own other leads.
                admin = next(p for p in summary.people if p.id == here.setup.state.person_id)
                assert admin.current.work == 0
                assert summary.timezone == "Asia/Kolkata"
                assert summary.start.isoformat() == "2026-09-29"
                assert summary.prior.isoformat() == "2026-08-30"

    run(exercise())


def test_summary_matches_feed_privacy_undo_attachments_and_permissions(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            lead = UUID(await here.add("Fictional Private", "98760 81002"))
            other_lead = UUID(await here.add("Fictional Hidden Desk", "98760 81003"))
            outsider = await seed(here.setup.engine, role="member")
            seller_id, admin_id = here.seller.person_id, here.setup.state.person_id
            async with here.setup.sessions() as db, db.begin():

                def event(kind: str, actor: UUID | None = seller_id, **data: Any) -> UUID:
                    key = uuid4()
                    db.add(
                        LeadEvent(
                            id=key,
                            tenant_id=here.tenant_id,
                            lead_id=lead,
                            kind=kind,
                            actor_person_id=actor,
                            data=data,
                            created_at=NOW - timedelta(hours=1),
                        )
                    )
                    return key

                private = event("call", via="phone", connected=True)
                public = event("call", via="phone", duration_seconds=12)
                event("call", for_call=str(public), recording=True)
                # An orphan recording remains one call.
                event("call", for_call=str(uuid4()))
                undone = event("note")
                event("note", actor=admin_id)
                event("message", actor=None)
                for index, (key, value) in enumerate(
                    ((private, True), (public, True), (public, False))
                ):
                    db.add(
                        LeadEvent(
                            id=uuid4(),
                            tenant_id=here.tenant_id,
                            lead_id=lead,
                            kind="edited",
                            actor_person_id=seller_id,
                            data={PRIVATE_CALL: str(key), "private": value},
                            created_at=NOW + timedelta(minutes=index + 1),
                        )
                    )
                event("edited", undo_of=str(undone))
                # Someone else's lead is unreadable to the seller, even with their actor id.
                from ac_platform.lead_desk.models import Lead

                hidden = await db.get(Lead, other_lead)
                assert hidden is not None
                hidden.owner_person_id = admin_id
                db.add(
                    LeadEvent(
                        id=uuid4(),
                        tenant_id=here.tenant_id,
                        lead_id=other_lead,
                        kind="note",
                        actor_person_id=seller_id,
                        data={},
                        created_at=NOW,
                    )
                )
                await db.flush()
                for viewer, team in (
                    (Viewer(admin_id, here.tenant_id, "admin", "Fictional Admin"), True),
                    (Viewer(seller_id, here.tenant_id, "member", "Fictional Seller"), False),
                    (Viewer(admin_id, here.tenant_id, "viewer", "Fictional Viewer"), True),
                ):
                    desk = LeadDesk(db, viewer, now=NOW)
                    summary = await summarize(desk, team=team)
                    feed = await desk.activity(day="recent", team=team)
                    visible = [item for item in feed.items if item.event.kind != "captured"]
                    assert summary.current.work == len(visible)
                    assert summary.current.calls == sum(
                        item.event.kind == "call" for item in visible
                    )
                    assert summary.current.calls == (3 if viewer.person_id == seller_id else 2)
                admin_desk = LeadDesk(
                    db, Viewer(admin_id, here.tenant_id, "admin", "Fictional Admin"), now=NOW
                )
                assert (await summarize(admin_desk, team=True)).current.notes == 2
                assert (await summarize(admin_desk, team=True, person=seller_id)).current.notes == 1
                mine = LeadDesk(
                    db, Viewer(seller_id, here.tenant_id, "member", "Fictional Seller"), now=NOW
                )
                assert (await summarize(mine)).current.notes == 0
                for options in ({"team": True}, {"person": admin_id}):
                    with pytest.raises(DeskError) as denied:
                        await summarize(mine, **options)
                    assert denied.value.status == 403
                empty = await summarize(
                    LeadDesk(
                        db,
                        Viewer(
                            outsider.person_id, outsider.tenant_id, "admin", "Fictional Outsider"
                        ),
                        now=NOW,
                    ),
                    team=True,
                )
                assert empty.current.work == empty.previous.work == 0
                assert all(p.current.work == 0 for p in empty.people)

    run(exercise())


def test_summary_api_contract_and_query_guards(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            here.as_admin()
            response = await here.client.get(f"{BASE}/activity/summary?days=30&team=true")
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["schema"] == "lead-desk/1" and body["days"] == 30
            assert body["timezone"] == "Asia/Kolkata"
            assert (
                body["current"]
                == body["previous"]
                == dict(calls=0, conversations=0, notes=0, moves=0, work=0)
            )
            assert len(body["people"]) == 2
            assert len(body["people"][0]["daily"]) == 60
            assert "no-store" in response.headers["cache-control"]
            assert "next_before" not in body
            for query in ("days=0", "days=91", "days=no", "before=2026-01-01", "person=no"):
                assert (
                    await here.client.get(f"{BASE}/activity/summary?{query}")
                ).status_code == 422
            here.as_seller()
            assert (await here.client.get(f"{BASE}/activity/summary?team=true")).status_code == 403
            assert (
                await here.client.get(
                    f"{BASE}/activity/summary?person={here.setup.state.person_id}"
                )
            ).status_code == 403
            assert (await here.client.get(f"{BASE}/activity/summary")).status_code == 200
            here.client.cookies.clear()
            assert (await here.client.get(f"{BASE}/activity/summary")).status_code == 401

    run(exercise())
