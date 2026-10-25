"""The day's digest, the two-hourly sweep and the hour's banner on PostgreSQL (demo, 26 Oct
2026): a seller with a phone gets the 10:00 digest once, with a count and no lead in it, and
its words on their own session; nothing between slots; the 12:00 sweep counts what is late
and new; the ledger takes a known kind only, and once written it requires forward recovery;
the banner names the soonest follow-up due within the hour, and nothing when none is.
Made-up people only."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, func, select, update
from sqlalchemy.exc import IntegrityError

from ac_platform.audit.models import AuditEvent
from ac_platform.identity.models import Person
from ac_platform.lead_desk import digest_push
from ac_platform.lead_desk.models import Lead, LeadDigest
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_desk_digests_migration_postgresql import migration
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, World, world

IST = ZoneInfo("Asia/Kolkata")
SCRIPT = Path(__file__).resolve().parents[2] / "scripts/data-changes/send-digests-now.py"
LOADER = importlib.util.spec_from_file_location("send_digests_now", SCRIPT)
assert LOADER is not None and LOADER.loader is not None
tool = importlib.util.module_from_spec(LOADER)
LOADER.loader.exec_module(tool)


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


async def pushed(here: World, now: datetime) -> list[digest_push.DigestAlert]:
    async with here.setup.sessions() as db, db.begin():
        alerts = await digest_push.collect(db, now)
    return [alert for alert in alerts if alert.tenant_id == here.tenant_id]


def test_digest_sweep_ledger_and_banner(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            today = datetime.now(IST).date()

            def at(hour: int, minute: int = 0, days: int = 0) -> datetime:
                return datetime.combine(
                    today + timedelta(days=days), time(hour, minute), tzinfo=IST
                )

            token = "fictional-phone-" + uuid4().hex
            registered = await here.client.post(
                f"{BASE}/devices", json={"token": token}, headers=WRITE
            )
            assert registered.status_code == 200, registered.text
            later = await here.add("Fictional Later Today", "98760 82001")
            late = await here.add("Fictional Late", "98760 82002")
            await here.add("Fictional New", "98760 82003")

            async def due(lead: str, when: datetime | None) -> None:
                async with here.setup.sessions() as db, db.begin():
                    await db.execute(
                        update(Lead).where(Lead.id == UUID(lead)).values(next_action_at=when)
                    )

            await due(later, at(23, 0))
            await due(late, at(9, 0, days=-1))

            digest = await pushed(here, at(10, 5))
            assert [(alert.kind, alert.count, alert.tokens) for alert in digest] == [
                ("digest", 2, [token])
            ]
            assert set(digest[0].data()) == {"type", "kind", "tenant", "count"}
            assert await pushed(here, at(10, 10)) == []  # once a slot
            assert await pushed(here, at(11, 0)) == []  # between slots
            sweep = await pushed(here, at(12, 10))
            assert [(alert.kind, alert.count) for alert in sweep] == [("sweep", 2)]

            said = await here.client.get(f"{BASE}/alert", params={"kind": "digest"})
            assert said.status_code == 200, said.text
            assert said.json()["title"] == "Today: 2 follow-ups"
            assert said.json()["url"] == "/leads?due=today"
            assert "Fictional" not in said.text
            swept = (await here.client.get(f"{BASE}/alert", params={"kind": "sweep"})).json()
            assert swept["title"].endswith("1 new lead") and "Fictional" not in swept["body"]

            # The ledger: a known kind only; once written, rollback needs forward recovery.
            async with here.setup.sessions() as db:
                with pytest.raises(IntegrityError):
                    async with db.begin():
                        db.add(
                            LeadDigest(
                                id=uuid4(),
                                tenant_id=here.tenant_id,
                                person_id=here.seller.person_id,
                                kind="hello",
                                slot=at(10),
                                counts={},
                                claimed_at=at(10),
                            )
                        )

            def downgrade(connection: Any) -> None:
                with Operations.context(MigrationContext.configure(connection)):
                    migration().downgrade()

            with pytest.raises(RuntimeError, match="requires forward recovery"):
                async with here.setup.engine.begin() as connection:
                    await connection.run_sync(downgrade)

            # The banner: nothing within the hour, then the soonest follow-up.
            now = datetime.now(IST)
            await due(later, now + timedelta(hours=3))
            nothing = await here.client.get(f"{BASE}/soon")
            assert nothing.status_code == 200, nothing.text
            assert nothing.json()["item"] is None
            await due(later, now + timedelta(minutes=40))
            item = (await here.client.get(f"{BASE}/soon")).json()["item"]
            assert item["lead_id"] == later and item["what"] == "follow_up"
            assert item["minutes"] in (39, 40)
            assert item["words"] == f"Fictional Later Today: follow-up in {item['minutes']} min"
            here.as_admin()
            assert (await here.client.get(f"{BASE}/soon")).json()["item"] is None  # not theirs
            # Outside work hours, the banner stays quiet.
            hour = now.hour
            start, end = ("13:00", "14:00") if hour < 12 or hour >= 15 else ("06:00", "07:00")
            revision = (await here.client.get(f"{BASE}/team")).json()["settings"]["revision"]
            hours = await here.client.put(
                f"{BASE}/work-hours",
                json={
                    "expected_revision": revision,
                    "days": [0, 1, 2, 3, 4, 5, 6],
                    "start": start,
                    "end": end,
                },
                headers=WRITE,
            )
            assert hours.status_code == 200, hours.text
            here.as_seller()
            assert (await here.client.get(f"{BASE}/soon")).json()["item"] is None

    run(exercise())


def test_on_demand_for_a_test_organisation_only(postgres_harness: Any, tmp_path: Path) -> None:
    """send-digests-now.py: the schedule's own path, forced now; a real organisation is
    refused without its flag; the dry run sends nothing and leaves no ledger row; the apply
    writes one row per kind and is audited (no FCM here, so nothing goes out)."""

    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            registered = await here.client.post(
                f"{BASE}/devices", json={"token": "fictional-phone-" + uuid4().hex}, headers=WRITE
            )
            assert registered.status_code == 200, registered.text
            lead = await here.add("Fictional Test Lead", "98760 82101")
            async with here.setup.sessions() as db, db.begin():
                await db.execute(
                    update(Lead)
                    .where(Lead.id == UUID(lead))
                    .values(next_action_at=datetime.now(IST) - timedelta(hours=2))
                )
                approver = await db.scalar(
                    select(Person.email).where(Person.id == here.setup.state.person_id)
                )
            spec = {
                "tenant": str(here.tenant_id),
                "kinds": ["digest", "sweep"],
                "approver_email": approver,
                "issue": "AUT-test",
            }
            sessions = here.setup.sessions
            now = datetime.now(IST)
            with pytest.raises(SystemExit, match="not_a_test_organisation"):
                await tool.execute(sessions, spec, mode="dry-run", now=now)
            async with sessions() as db, db.begin():
                await db.execute(
                    update(Lead).where(Lead.tenant_id == here.tenant_id).values(test_data=True)
                )
            dry = await tool.execute(sessions, spec, mode="dry-run", now=now)
            assert dry["status"] == "rehearsed_and_rolled_back"
            assert sorted((p["kind"], p["count"], p["phones"]) for p in dry["pushes"]) == [
                ("digest", 1, 1),
                ("sweep", 1, 1),
            ]

            async def rows() -> int:
                async with sessions() as db:
                    return int(
                        await db.scalar(
                            select(func.count())
                            .select_from(LeadDigest)
                            .where(LeadDigest.tenant_id == here.tenant_id)
                        )
                        or 0
                    )

            assert await rows() == 0
            done = await tool.execute(sessions, spec, mode="apply", now=now)
            assert done["status"] == "ledger_written_but_fcm_not_configured"
            assert await rows() == 2
            async with sessions() as db:
                audited = await db.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action == tool.ACTION, AuditEvent.tenant_id == here.tenant_id)
                )
            assert audited == 1

    run(exercise())
