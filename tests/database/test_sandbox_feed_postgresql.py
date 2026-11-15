"""The dev sandbox feed on PostgreSQL (owner, 15 Nov 2026: "data keeps coming live every day
in proper working hours"): on a small sandbox the generator builds, setup adds the sixth
seller, the work hours and the drawn avatars and moves typed-in leads to History; a dry run
leaves nothing; a tick plays the day up to now minus the lag through the app's own desk
(calls the phone logs inside work hours, never ending after now, Connected never above
Attempted) and keeps its cursor in one audit event, so the same tick again plays nothing;
and the feed refuses anywhere but development and anything but the sandbox."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Engine, func, select

from ac_platform.audit.models import AuditEvent
from ac_platform.identity.models import Person
from ac_platform.identity.password_auth import hash_password
from ac_platform.identity.sales_xray_profile_models import PersonPhoto
from ac_platform.lead_desk.models import Lead, LeadEvent
from ac_platform.lead_desk.store import counted_phone_call
from ac_platform.tenancy.models import Membership
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import ROOT, world

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(name: str, path: Path):  # type: ignore[no-untyped-def]
    found = importlib.util.spec_from_file_location(name, path)
    assert found is not None and found.loader is not None
    module = importlib.util.module_from_spec(found)
    sys.modules[name] = module
    found.loader.exec_module(module)
    return module


generator = _load(
    "sandbox_organisations_feed_db", SCRIPTS / "data-changes/sandbox-organisations.py"
)
feed = _load("sandbox_feed_db", SCRIPTS / "sandbox_feed/feed.py")
IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_setup_tick_cursor_and_refusals(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            sessions = here.setup.sessions
            async with sessions() as db:
                owner = await db.scalar(
                    select(Person.email).where(Person.id == here.setup.state.person_id)
                )
                coach = await db.scalar(
                    select(Person.email).where(Person.id == here.seller.person_id)
                )
            assert owner and coach
            # A small sandbox ending last night, built by the generator the feed builds on.
            last = datetime.now(UTC).astimezone(IST).date() - timedelta(days=1)
            raw = {
                "command_id": "8d2f6a10-15b1-4e2c-9a77-15112026feed",
                "approver_email": owner,
                "issue": "owner chat 15 Nov 2026",
                "owner_email": owner,
                "admin_email": coach,
                "seller_mailbox": "owner@example.test",
                "organisations": ["ac"],
                "days": 4,
                "scale": 0.3,
                "end": last.isoformat(),
                "require_pipeline": False,
            }
            emails = generator.logins(generator.spec_of(json.dumps(raw)))["ac"]
            raw["password_hashes"] = {
                email: hash_password("fictional-sandbox-login-1") for email in emails
            }
            boundaries = (uuid4(), uuid4())
            [built] = await generator.execute(
                sessions,
                generator.spec_of(json.dumps(raw)),
                mode="apply",
                now=datetime.now(UTC),
                boundaries=boundaries,
            )
            tenant = UUID(built["after"]["tenant_id"])
            # A lead typed in by hand (a tester's) sits in the sandbox too.
            async with sessions() as db:
                typed = await db.scalar(select(Lead).where(Lead.tenant_id == tenant).limit(1))
                assert typed is not None
                typed.source = "manual"
                typed_id = typed.id
                await db.commit()

            async def count(model: Any, *where: Any) -> int:
                async with sessions() as db:
                    return int(
                        await db.scalar(select(func.count()).select_from(model).where(*where)) or 0
                    )

            options: dict[str, Any] = {"tenant_id": tenant, "environment": "development"}

            # Anywhere but development, or anything but the sandbox: refused, nothing made.
            with pytest.raises(feed.Refused):
                await feed.run(
                    sessions,
                    "tick",
                    apply=True,
                    now=datetime.now(UTC),
                    tenant_id=tenant,
                    environment="staging",
                )
            with pytest.raises(feed.Refused):
                await feed.run(
                    sessions,
                    "tick",
                    apply=True,
                    now=datetime.now(UTC),
                    tenant_id=uuid4(),
                    environment="development",
                )

            # Setup: the sixth seller, the hours, avatars, the typed-in lead to History.
            [setup] = await feed.run(
                sessions,
                "setup",
                apply=True,
                now=datetime.now(UTC),
                boundaries=boundaries,
                **options,
            )
            assert setup["newcomer"] == "made+joined"
            assert setup["to_history"] == {"typed_in": 1}
            assert setup["avatars_drawn"] == 6
            # Six sellers, and the owner, who closes the leads the coach hands him.
            assert len(setup["sellers"]) == 7
            async with sessions() as db:
                moved = await db.scalar(select(Lead).where(Lead.id == typed_id))
                assert moved is not None and moved.pipeline == "history"
                members = (
                    await db.scalars(
                        select(Membership.person_id).where(
                            Membership.tenant_id == tenant, Membership.role == "member"
                        )
                    )
                ).all()
            assert len(members) == 6
            assert await count(PersonPhoto, PersonPhoto.person_id.in_(members)) == 6
            again = await feed.run(
                sessions,
                "setup",
                apply=True,
                now=datetime.now(UTC),
                boundaries=boundaries,
                **options,
            )
            assert again[0]["newcomer"] == "found" and again[0]["avatars_drawn"] == 0

            # A working afternoon today (India time).
            today = last + timedelta(days=1)
            now = datetime.combine(today, time(16, 0), tzinfo=IST).astimezone(UTC)
            calls_before = await count(
                LeadEvent, LeadEvent.tenant_id == tenant, LeadEvent.kind == "call"
            )

            # A dry run plays it all and leaves nothing.
            [dry] = await feed.run(sessions, "tick", apply=False, now=now, **options)
            assert dry["made"].get("calls", 0) > 0 and dry["applied"] is False
            assert await count(AuditEvent, AuditEvent.action == feed.ACTION) == 0
            assert (
                await count(LeadEvent, LeadEvent.tenant_id == tenant, LeadEvent.kind == "call")
                == calls_before
            )

            [tick] = await feed.run(sessions, "tick", apply=True, now=now, **options)
            assert tick["applied"] is True
            made = tick["made"]
            assert made["calls"] > 10
            assert made["connected"] <= made["calls"]
            # No authored reports in this database: the reports step says so and moves on.
            assert made.get("reports_source_missing") == 1
            # Each lead the coach hands the owner gets a call booked for later today.
            assert made.get("owner_follow_ups", 0) == made.get("handed_to_owner", 0)
            until = datetime.fromisoformat(tick["until"])
            assert until == now - feed.LAG
            async with sessions() as db:
                rows = (
                    await db.execute(
                        select(LeadEvent.created_at, LeadEvent.data).where(
                            LeadEvent.tenant_id == tenant,
                            LeadEvent.kind == "call",
                            LeadEvent.created_at > datetime.fromisoformat(tick["cursor"]),
                        )
                    )
                ).all()
            phone = [data for _, data in rows if counted_phone_call(data)]
            assert len(phone) >= made["calls"]
            for created, _ in rows:
                # Each call sits inside the work hours, and none after now.
                assert created <= now
                assert feed.OPENS <= created.astimezone(IST).time() <= feed.CLOSES
            connected = sum(int(data.get("duration_seconds") or 0) > 0 for data in phone)
            assert connected <= len(phone)
            assert await count(AuditEvent, AuditEvent.action == feed.ACTION) == 1

            # The same tick again: the cursor says it is played; nothing new.
            [same] = await feed.run(sessions, "tick", apply=True, now=now, **options)
            assert same.get("nothing_to_play") is True
            assert await count(AuditEvent, AuditEvent.action == feed.ACTION) == 1

            # Today's read-back is the stored calls, per seller.
            [read] = await feed.run(sessions, "read", apply=False, now=now, **options)
            team = read["today"]["team"]
            # Nothing happened today before the tick (the build ended at midnight), and the
            # tick also played last evening: today's calls are a part of the tick's.
            assert 0 < team["calls"] <= len(phone)
            assert team["connected"] <= team["calls"]
            assert set(read["today"]["sellers"]) == set(setup["sellers"])
            assert read["cursor"] == tick["until"]

    run(exercise())


def test_the_days_shape_is_stable_across_ticks() -> None:
    day = date(2026, 11, 16)
    seller = feed.PROFILES["ac.rohan"]
    assert feed.work_day(seller, day) == feed.work_day(seller, day)
