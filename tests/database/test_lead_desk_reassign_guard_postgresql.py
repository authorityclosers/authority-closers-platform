"""Auto-reassign's guard rails (Wise Life's first day with it, 20 Nov 2026), on PostgreSQL.

- A call tap, a message from the app, a phone-logged call of 10 s or more, or a note by the
  lead's owner stops the 30-work-minute clock; the first three and the note also set first
  contact. A manager's note, or a 5 s phone-logged call, does not.
- At most two automatic moves a lead a day, never back to someone it left today; then it
  waits for a manager ("Needs a manager", no owner, a bell line for the admin).
- Only leads given out after the rule was switched on move; switching on records when.
- A seller away from the app is skipped; with everyone away the lead waits for a manager.
- A lead a seller added for themselves never moves by itself.
- Every automatic move adds an audit event.

Made-up people only.
"""

from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.models import AuditEvent
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.lead_desk import reassign_guard
from ac_platform.lead_desk.contracts import MessageSent, NoteCommand
from ac_platform.lead_desk.models import Lead, LeadDeskSettings, LeadEvent
from ac_platform.lead_desk.store import LeadDesk, Viewer
from ac_platform.product_updates.models import Notification
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation
from tests.database.test_lead_desk_split_and_give_postgresql import _config

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
BASE = "/v1/lead-desk"
IST = ZoneInfo("Asia/Kolkata")
ALL_DAY = {"days": [0, 1, 2, 3, 4, 5, 6], "start": "00:00", "end": "23:59", "pause_leads": False}


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def _noon() -> datetime:
    """Midday today in India: every sweep below falls on the same Indian day."""
    return datetime.combine(datetime.now(IST).date(), time(12), tzinfo=IST).astimezone(UTC)


def _robot(setup: Any) -> Viewer:
    return Viewer(
        person_id=UUID(int=0), tenant_id=setup.state.tenant_id, role="owner", name="Auto-reassign"
    )


async def _world(setup: Any, *, since: datetime | None) -> list[UUID]:
    await _organisation(setup)  # the signed-in person is an admin, who doesn't sell
    sellers = [
        (await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")).person_id
        for _ in range(3)
    ]
    values: dict[str, Any] = {
        "auto_reassign": True,
        "reassign_minutes": 30,
        "work_hours": ALL_DAY,
    }
    if since is not None:
        values[reassign_guard.ENABLED_AT] = since.isoformat()
    await _config(setup, **values)
    return sellers


async def _seen(setup: Any, person: UUID, at: datetime) -> None:
    async with AsyncSession(setup.engine) as db, db.begin():
        await db.execute(
            update(IdentitySession)
            .where(IdentitySession.person_id == person)
            .values(last_seen_at=at)
        )


async def _add(client: httpx.AsyncClient, name: str, phone: str, assign: str = "rules") -> UUID:
    added = await client.post(
        f"{BASE}/leads",
        json={"command_id": str(uuid4()), "name": name, "phone": phone, "assign": assign},
        headers=WRITE,
    )
    assert added.status_code == 201, added.text
    return UUID(added.json()["lead"]["lead_id"])


async def _given(setup: Any, lead_id: UUID, at: datetime, owner: UUID | None = None) -> UUID:
    """The lead was given out at ``at`` (to ``owner`` when named); its owner now."""
    async with AsyncSession(setup.engine) as db, db.begin():
        values: dict[str, Any] = {"assigned_at": at}
        if owner is not None:
            values["owner_person_id"] = owner
        await db.execute(update(Lead).where(Lead.id == lead_id).values(**values))
        found = await db.scalar(select(Lead.owner_person_id).where(Lead.id == lead_id))
    assert found is not None
    return found


async def _sweep(setup: Any, now: datetime) -> tuple[int, dict[str, int]]:
    async with AsyncSession(setup.engine) as db, db.begin():
        desk = LeadDesk(db, _robot(setup), now=now)
        moved = await desk.sweep()
        return moved, dict(desk.reassign_tally.counts)


async def _lead(setup: Any, lead_id: UUID) -> Lead:
    async with AsyncSession(setup.engine, expire_on_commit=False) as db:
        found = await db.get(Lead, lead_id)
    assert found is not None
    return found


def test_two_moves_a_day_then_a_manager_and_never_back(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            noon = _noon()
            sellers = await _world(setup, since=noon - timedelta(hours=2))
            for seller in sellers:
                await _seen(setup, seller, noon)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                lead_id = await _add(client, "Fictional Hot Potato", "98760 82001")
            first = await _given(setup, lead_id, noon - timedelta(minutes=31))

            assert (await _sweep(setup, noon))[0] == 1
            second = (await _lead(setup, lead_id)).owner_person_id
            assert second not in {None, first}
            for seller in sellers:
                await _seen(setup, seller, noon + timedelta(minutes=31))
            assert (await _sweep(setup, noon + timedelta(minutes=31)))[0] == 1
            third = (await _lead(setup, lead_id)).owner_person_id
            # Never back to someone it left today.
            assert third not in {None, first, second}

            for seller in sellers:
                await _seen(setup, seller, noon + timedelta(minutes=62))
            moved, tally = await _sweep(setup, noon + timedelta(minutes=62))
            assert moved == 0 and tally.get("needs_manager_cap") == 1
            waiting = await _lead(setup, lead_id)
            assert waiting.owner_person_id is None and waiting.assigned_at is None
            assert (waiting.owner_reason or "").startswith(reassign_guard.NEEDS_MANAGER)
            # Unowned, it never moves round again.
            assert (await _sweep(setup, noon + timedelta(minutes=95)))[0] == 0

            async with AsyncSession(setup.engine) as db:
                hops = (
                    await db.scalars(
                        select(LeadEvent)
                        .where(LeadEvent.lead_id == lead_id, LeadEvent.kind == "reassigned")
                        .order_by(LeadEvent.created_at)
                    )
                ).all()
                assert [event.data.get("hop") for event in hops] == [1, 2, 3]
                assert all(event.data.get("auto") == reassign_guard.NO_CALL for event in hops)
                assert hops[-1].data.get("why") == "cap"
                audits = (
                    await db.scalars(
                        select(AuditEvent).where(
                            AuditEvent.tenant_id == setup.state.tenant_id,
                            AuditEvent.resource_id == str(lead_id),
                        )
                    )
                ).all()
                actions = sorted(audit.action for audit in audits)
                assert actions == sorted(
                    [reassign_guard.AUDIT_MOVED] * 2 + [reassign_guard.AUDIT_WAITING]
                )
                rung = (
                    await db.scalars(
                        select(Notification).where(
                            Notification.person_id == setup.state.person_id,
                            Notification.dedupe_key.startswith("lead-needs-manager:"),
                        )
                    )
                ).all()
                assert len(rung) == 1 and rung[0].urgent
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_any_contact_stops_the_clock(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            noon = _noon()
            sellers = await _world(setup, since=noon - timedelta(hours=2))
            for seller in sellers:
                await _seen(setup, seller, noon)
            names = (
                "tapped",
                "messaged",
                "noted",
                "logged_long",
                "logged_short",
                "untouched",
                "manager_note",
            )
            ids: dict[str, UUID] = {}
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                for number, name in enumerate(names):
                    ids[name] = await _add(client, f"Fictional {name}", f"98760 830{number:02d}")
            owners = {
                name: await _given(setup, lead_id, noon - timedelta(minutes=31))
                for name, lead_id in ids.items()
            }

            def as_owner(name: str, db: AsyncSession) -> LeadDesk:
                return LeadDesk(
                    db,
                    Viewer(
                        person_id=owners[name],
                        tenant_id=setup.state.tenant_id,
                        role="member",
                        name="Fictional Seller",
                    ),
                    now=noon - timedelta(minutes=20),
                )

            async with AsyncSession(setup.engine) as db, db.begin():
                await as_owner("tapped", db).record_call(
                    ids["tapped"],
                    command_id=uuid4(),
                    submission_id=None,
                    simulated=False,
                    duration_seconds=None,
                    away=True,
                )
            async with AsyncSession(setup.engine) as db, db.begin():
                await as_owner("messaged", db).message(
                    ids["messaged"], MessageSent(command_id=uuid4(), channel="whatsapp")
                )
            async with AsyncSession(setup.engine) as db, db.begin():
                await as_owner("noted", db).note(
                    ids["noted"], NoteCommand(command_id=uuid4(), note="Asked for a callback")
                )
            async with AsyncSession(setup.engine) as db, db.begin():
                # Calls the phone logged (written as the phone sync writes their lines).
                for name, seconds in (("logged_long", 12), ("logged_short", 5)):
                    desk = as_owner(name, db)
                    lead = await db.get(Lead, ids[name])
                    assert lead is not None
                    desk._event(
                        lead,
                        "call",
                        {"via": "phone", "direction": "outgoing", "duration_seconds": seconds},
                        actor=owners[name],
                    )
            async with AsyncSession(setup.engine) as db, db.begin():
                admin = LeadDesk(
                    db,
                    Viewer(
                        person_id=setup.state.person_id,
                        tenant_id=setup.state.tenant_id,
                        role="admin",
                        name="Fictional Admin",
                    ),
                    now=noon - timedelta(minutes=20),
                )
                await admin.note(
                    ids["manager_note"], NoteCommand(command_id=uuid4(), note="Call her today")
                )

            for name in ("tapped", "messaged", "noted"):
                assert (await _lead(setup, ids[name])).first_contact_at is not None, name
            assert (await _lead(setup, ids["manager_note"])).first_contact_at is None

            moved, _ = await _sweep(setup, noon)
            assert moved == 3
            for name, lead_id in ids.items():
                owner = (await _lead(setup, lead_id)).owner_person_id
                if name in {"logged_short", "untouched", "manager_note"}:
                    assert owner not in {None, owners[name]}, name
                else:
                    assert owner == owners[name], name
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_only_new_givings_move_and_never_to_someone_away(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            noon = _noon()
            # Switched on before the switch kept its time: the first pass records it.
            sellers = await _world(setup, since=None)
            here, gone, there = sellers
            for seller in sellers:
                await _seen(setup, seller, noon)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                before = await _add(client, "Fictional Before", "98760 84001")
                after = await _add(client, "Fictional After", "98760 84002")
                last = await _add(client, "Fictional Last", "98760 84003")
                # A seller adds a lead for themselves: theirs, it never moves by itself.
                state = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
                client.cookies.set(setup.settings.session_cookie_name, await _session(setup, state))
                own = await _add(client, "Fictional Own", "98760 84004", assign="me")
                await _seen(setup, state.person_id, noon)
                # Given out just now: not due in the first passes below.
                await _given(setup, last, noon, owner=here)

                assert await _sweep(setup, noon - timedelta(hours=1)) == (0, {"enabled_at_set": 1})
                async with AsyncSession(setup.engine) as db:
                    row = await db.get(LeadDeskSettings, setup.state.tenant_id)
                    assert row is not None
                    since = reassign_guard.enabled_at(row.config)
                assert since == noon - timedelta(hours=1)

                await _given(setup, before, since - timedelta(minutes=1), owner=here)
                await _given(setup, after, noon - timedelta(minutes=31), owner=here)
                await _given(setup, own, noon - timedelta(minutes=31))
                # One seller hasn't opened the app for five work hours: away.
                await _seen(setup, gone, noon - timedelta(hours=5))
                moved, tally = await _sweep(setup, noon)
                assert moved == 1 and tally.get("own_pick") == 1
                assert (await _lead(setup, before)).owner_person_id == here
                assert (await _lead(setup, own)).owner_person_id == state.person_id
                assert (await _lead(setup, after)).owner_person_id in {there, state.person_id}

                # Everyone else away: it waits for a manager instead.
                await _seen(setup, there, noon - timedelta(hours=5))
                await _seen(setup, state.person_id, noon - timedelta(hours=5))
                await _given(setup, last, noon - timedelta(minutes=31), owner=here)
                moved, tally = await _sweep(setup, noon + timedelta(minutes=5))
                assert moved == 0 and tally.get("needs_manager_away") == 1
                waiting = await _lead(setup, last)
                assert waiting.owner_person_id is None
                assert (waiting.owner_reason or "").startswith(reassign_guard.NEEDS_MANAGER)

                # A manager switching it off and on records the new time.
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                team = (await client.get(f"{BASE}/team")).json()
                for on in (False, True):
                    saved = await client.put(
                        f"{BASE}/settings",
                        json={
                            "expected_revision": team["settings"]["revision"],
                            "auto_reassign": on,
                            "reassign_minutes": 30,
                        },
                        headers=WRITE,
                    )
                    assert saved.status_code == 200, saved.text
                    team = saved.json()
                    async with AsyncSession(setup.engine) as db:
                        row = await db.get(LeadDeskSettings, setup.state.tenant_id)
                        assert row is not None
                        stored = reassign_guard.enabled_at(row.config)
                    assert (stored is not None) is on
                    assert stored is None or stored > since
        finally:
            await setup.engine.dispose()

    run(exercise())
