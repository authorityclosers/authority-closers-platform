"""Fictional settlement receipts prove per-day dashboard activity in one statement."""

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.conversation_intelligence.acquisition_activity import (
    account_activity,
    organisation_acquisition_activity,
)
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement,
    ConversationAcquisitionUsage,
    ConversationVisitor,
    ConversationVisitorClaim,
)
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.application import ConversationDenied
from ac_platform.conversation_intelligence.canary_models import ConversationCanarySubmission
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership, Organisation
from tests.database.test_conversation_account_library_postgresql import (
    postgres_harness,  # noqa: F401 - shared disposable PostgreSQL fixture
)
from tests.database.test_conversation_postgresql import run, seed

# 12:00Z is 17:30 in Asia/Kolkata, so "today" is 29 Sep and the first entry 31 Aug.
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
FIRST, TODAY = date(2026, 8, 31), date(2026, 9, 29)


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def _receipt(
    db: AsyncSession,
    tenant_id: UUID,
    settled_at: datetime | None,
    *,
    person_id: UUID | None = None,
    visitor_id: UUID | None = None,
    seconds: int = 60,
    kind: str = "completed",
) -> UUID:
    """Usage with no recording row: the receipt outlives the deleted recording."""
    usage = ConversationAcquisitionUsage(
        id=uuid4(),
        tenant_id=tenant_id,
        person_id=person_id,
        visitor_id=visitor_id,
        submission_id=uuid4(),
        source_sha256=_digest(f"source-{uuid4()}"),
        duration_evidence_sha256=_digest("fictional-duration"),
        reserved_seconds=max(seconds, 1) + 100,
        policy_revision="guest-processing-v1",
        created_at=(settled_at or NOW) - timedelta(minutes=5),
    )
    db.add(usage)
    await db.flush()
    if settled_at is not None:
        db.add(
            ConversationAcquisitionSettlement(
                usage_id=usage.id,
                charged_seconds=seconds if kind == "completed" else 0,
                kind=kind,
                receipt_sha256=_digest(f"receipt-{usage.id}"),
                created_at=settled_at,
            )
        )
        await db.flush()
    return usage.submission_id


async def _visitor(db: AsyncSession, tenant_id: UUID) -> UUID:
    visitor = ConversationVisitor(
        id=uuid4(),
        tenant_id=tenant_id,
        token_hash=uuid4().bytes * 2,
        created_at=NOW - timedelta(days=3),
        expires_at=NOW + timedelta(days=3),
    )
    db.add(visitor)
    await db.flush()
    return visitor.id


def test_activity_buckets_owned_completed_receipts_by_kolkata_day(postgres_harness):  # noqa: F811
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            state = await seed(engine)
            other = await seed(engine, tenant_id=state.tenant_id)
            foreign = await seed(engine)
            tenant = state.tenant_id

            async def read(actor, statements=None):
                async with sessions() as db, db.begin():
                    ownership = GuestOwnership(
                        AcquisitionSessions(
                            db,
                            tenant_id=actor.tenant_id,
                            policy_revision="guest-processing-v1",
                            clock=lambda: NOW,
                        )
                    )
                    if statements is None:
                        return await account_activity(ownership, actor)
                    await ownership.sessions._owner(None, actor, await ownership.sessions._admit())

                    def capture(conn, cursor, statement, parameters, context, executemany):
                        statements.append(statement)

                    event.listen(engine.sync_engine, "before_cursor_execute", capture)
                    try:
                        await ownership.sessions._owner(
                            None, actor, await ownership.sessions._admit()
                        )
                        admission = len(statements)
                        statements.clear()
                        result = await account_activity(ownership, actor)
                    finally:
                        event.remove(engine.sync_engine, "before_cursor_execute", capture)
                    assert len(statements) == admission + 1
                    assert all(s.lstrip().upper().startswith("SELECT") for s in statements)
                    return result

            empty = await read(state.actor)
            assert empty == {
                "timezone": "Asia/Kolkata",
                "days": [
                    {
                        "date": (FIRST + timedelta(days=offset)).isoformat(),
                        "analysed": 0,
                        "analysed_seconds": 0,
                    }
                    for offset in range(30)
                ],
                "analysed_last_30_days": 0,
                "analysed_previous_30_days": 0,
            }
            assert empty["days"][-1]["date"] == TODAY.isoformat()

            async with sessions() as db, db.begin():
                own = dict(person_id=state.person_id)
                # IST midnight: 18:29:59Z is 27 Sep, 18:30:00Z is 28 Sep.
                await _receipt(db, tenant, _at("2026-09-27T18:29:59"), seconds=90, **own)
                await _receipt(db, tenant, _at("2026-09-27T18:30:00"), seconds=120, **own)
                await _receipt(db, tenant, _at("2026-09-29T11:00:00"), seconds=30, **own)
                # First-entry edge (31 Aug 00:00 IST) and previous-window edges.
                await _receipt(db, tenant, _at("2026-08-30T18:30:00"), seconds=45, **own)
                await _receipt(db, tenant, _at("2026-08-30T18:29:59"), **own)
                await _receipt(db, tenant, _at("2026-07-31T18:30:00"), **own)
                await _receipt(db, tenant, _at("2026-07-31T18:29:59"), **own)
                # A guest upload this person claimed counts; an unclaimed one does not.
                claimed = await _visitor(db, tenant)
                db.add(
                    ConversationVisitorClaim(
                        visitor_id=claimed,
                        tenant_id=tenant,
                        person_id=state.person_id,
                        session_id=state.session_id,
                        created_at=NOW - timedelta(days=2),
                    )
                )
                await db.flush()
                await _receipt(
                    db, tenant, _at("2026-09-28T04:00:00"), seconds=15, visitor_id=claimed
                )
                unclaimed = await _visitor(db, tenant)
                await _receipt(db, tenant, _at("2026-09-28T04:00:00"), visitor_id=unclaimed)
                # Excluded: no work performed, unsettled usage, canary, other owners.
                await _receipt(
                    db, tenant, _at("2026-09-28T05:00:00"), kind="no_work_performed", **own
                )
                await _receipt(db, tenant, None, **own)
                canary = await _receipt(db, tenant, _at("2026-09-28T06:00:00"), **own)
                db.add(
                    ConversationCanarySubmission(
                        tenant_id=tenant,
                        submission_id=canary,
                        environment="test",
                        fixture_sha256=_digest("fictional-canary"),
                        created_at=NOW,
                    )
                )
                await _receipt(db, tenant, _at("2026-09-28T07:00:00"), person_id=other.person_id)
                await _receipt(
                    db, foreign.tenant_id, _at("2026-09-28T08:00:00"), person_id=foreign.person_id
                )

            statements: list[str] = []
            activity = await read(state.actor, statements)
            nonzero = {day["date"]: day for day in activity["days"] if day["analysed"]}
            assert nonzero == {
                "2026-08-31": {"date": "2026-08-31", "analysed": 1, "analysed_seconds": 45},
                "2026-09-27": {"date": "2026-09-27", "analysed": 1, "analysed_seconds": 90},
                "2026-09-28": {"date": "2026-09-28", "analysed": 2, "analysed_seconds": 135},
                "2026-09-29": {"date": "2026-09-29", "analysed": 1, "analysed_seconds": 30},
            }
            assert len(activity["days"]) == 30
            assert activity["analysed_last_30_days"] == 5
            # 30 Aug 23:59:59 IST and 1 Aug 00:00 IST; 31 Jul 23:59:59 IST is outside.
            assert activity["analysed_previous_30_days"] == 2
            other_activity = await read(other.actor)
            assert other_activity["analysed_last_30_days"] == 1
            assert other_activity["analysed_previous_30_days"] == 0
        finally:
            await engine.dispose()

    run(exercise())


def test_organisation_receipts_authority_windows_attribution_and_fixed_queries(
    postgres_harness,  # noqa: F811
    tmp_path,
):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            owner = await seed(engine, role="owner")
            admin, former, masked = [
                await seed(engine, tenant_id=owner.tenant_id, role=role)
                for role in ("admin", "member", "member")
            ]
            personal, foreign = [await seed(engine, role="owner") for _ in range(2)]
            async with sessions() as db, db.begin():
                for state in (owner, foreign):
                    db.add(
                        Organisation(
                            tenant_id=state.tenant_id,
                            creation_command_id=uuid4(),
                            domain_verification_token="fictional-organisation-" + "x" * 43,
                        )
                    )
                for state, name in (
                    (owner, "Zoe"),
                    (admin, "Alex"),
                    (former, "Alex"),
                    (masked, None),
                ):
                    await db.execute(
                        update(Person)
                        .where(Person.id == state.person_id)
                        .values(
                            display_name=name, email=f"masked-{state.person_id.hex}@example.test"
                        )
                    )
                await db.execute(
                    update(Membership)
                    .where(
                        Membership.tenant_id == owner.tenant_id,
                        Membership.person_id == former.person_id,
                    )
                    .values(status="inactive", ended_at=NOW)
                )

            def ownership(db, actor, operations=None):
                return GuestOwnership(
                    AcquisitionSessions(
                        db,
                        tenant_id=actor.tenant_id,
                        policy_revision="guest-processing-v1",
                        clock=lambda: NOW,
                        operations_tenant_id=operations,
                    )
                )

            counts = []

            async def read(actor):
                async with sessions() as db, db.begin():
                    service = ownership(db, actor)
                    statements = []

                    def capture(conn, cursor, statement, parameters, context, executemany):
                        statements.append(statement)

                    event.listen(engine.sync_engine, "before_cursor_execute", capture)
                    try:
                        now = await service.sessions._admit()
                        await service.sessions._owner(None, actor, now, shared_identity_locks=True)
                        assert await service.organisation_call_reader(actor)
                        overhead = len(statements)
                        statements.clear()
                        body = await organisation_acquisition_activity(
                            service, actor, shared_identity_locks=True
                        )
                    finally:
                        event.remove(engine.sync_engine, "before_cursor_execute", capture)
                    assert len(statements) == overhead + 1
                    assert all(s.lstrip().upper().startswith("SELECT") for s in statements)
                    receipts = [
                        s for s in statements if "conversation_acquisition_settlements" in s
                    ]
                    assert len(receipts) == 1 and "GROUP BY" in receipts[0]
                    counts.append(len(statements))
                    return body

            empty = await read(owner.actor)
            assert empty == {**account_empty_body(), "people": []}
            async with sessions() as db, db.begin():
                for stamp, seconds in (
                    ("2026-09-27T18:29:59", 90),
                    ("2026-09-27T18:30:00", 120),
                    ("2026-09-29T11:00:00", 30),
                    ("2026-08-30T18:30:00", 45),
                    ("2026-08-30T18:29:59", 60),
                    ("2026-07-31T18:30:00", 60),
                    ("2026-07-31T18:29:59", 60),
                    ("2026-09-29T18:30:00", 60),
                ):
                    await _receipt(
                        db, owner.tenant_id, _at(stamp), person_id=owner.person_id, seconds=seconds
                    )
                claimed = await _visitor(db, owner.tenant_id)
                db.add(
                    ConversationVisitorClaim(
                        visitor_id=claimed,
                        tenant_id=owner.tenant_id,
                        person_id=admin.person_id,
                        session_id=admin.session_id,
                        created_at=NOW - timedelta(days=2),
                    )
                )
                await db.flush()
                await _receipt(db, owner.tenant_id, NOW, visitor_id=claimed, seconds=15)
                await _receipt(
                    db, owner.tenant_id, NOW, visitor_id=await _visitor(db, owner.tenant_id)
                )
                await _receipt(
                    db, owner.tenant_id, NOW, person_id=owner.person_id, kind="no_work_performed"
                )
                await _receipt(db, owner.tenant_id, None, person_id=owner.person_id)
                canary = await _receipt(db, owner.tenant_id, NOW, person_id=owner.person_id)
                db.add(
                    ConversationCanarySubmission(
                        tenant_id=owner.tenant_id,
                        submission_id=canary,
                        environment="test",
                        fixture_sha256=_digest("fictional-canary"),
                        created_at=NOW,
                    )
                )
                for state in (former, masked):
                    await _receipt(
                        db, owner.tenant_id, _at("2026-08-15T12:00:00"), person_id=state.person_id
                    )
                for state in (personal, foreign):
                    db.add(
                        Membership(
                            tenant_id=state.tenant_id, person_id=owner.person_id, role="member"
                        )
                    )
                    await db.flush()
                    await _receipt(db, state.tenant_id, NOW, person_id=owner.person_id)
                await _receipt(db, owner.tenant_id, NOW, person_id=owner.person_id, seconds=20)

            body = await read(owner.actor)
            assert await read(admin.actor) == body
            expected_days = account_empty_body()["days"]
            for offset, count, seconds in ((0, 1, 45), (27, 1, 90), (28, 1, 120), (29, 3, 65)):
                expected_days[offset].update(analysed=count, analysed_seconds=seconds)
            people = [
                dict(
                    person_id=str(state.person_id),
                    name=name,
                    analysed_last_30_days=count,
                    analysed_seconds_last_30_days=seconds,
                    analysed_previous_30_days=previous,
                )
                for state, name, count, seconds, previous in (
                    (owner, "Zoe", 5, 305, 2),
                    (admin, "Alex", 1, 15, 0),
                    (former, "Alex", 0, 0, 1),
                    (masked, "m***@example.test", 0, 0, 1),
                )
            ]
            assert body == dict(
                timezone="Asia/Kolkata",
                days=expected_days,
                analysed_last_30_days=6,
                analysed_previous_30_days=4,
                people=sorted(people, key=lambda p: (p["name"], p["person_id"])),
            )
            assert sum(d["analysed"] for d in body["days"]) == sum(
                p["analysed_last_30_days"] for p in body["people"]
            )
            assert sum(d["analysed_seconds"] for d in body["days"]) == sum(
                p["analysed_seconds_last_30_days"] for p in body["people"]
            )
            assert "masked-" not in json.dumps(body)
            (tmp_path / "organisation-activity.json").write_text(json.dumps(body, indent=2) + "\n")
            async with sessions() as db, db.begin():
                for offset, state in enumerate((owner, admin, masked)):
                    await _receipt(
                        db,
                        owner.tenant_id,
                        NOW - timedelta(days=offset + 5),
                        person_id=state.person_id,
                    )
            assert (await read(owner.actor))["analysed_last_30_days"] == 9
            assert len(set(counts)) == 1
            assert (await read(foreign.actor))["analysed_last_30_days"] == 1
            for actor, operations in (
                (masked.actor, None),
                (former.actor, None),
                (personal.actor, None),
                (owner.actor, owner.tenant_id),
                (ActorContext(foreign.person_id, foreign.session_id, owner.tenant_id), None),
            ):
                async with sessions() as db, db.begin():
                    with pytest.raises(ConversationDenied):
                        await organisation_acquisition_activity(
                            ownership(db, actor, operations), actor
                        )
            # Reuse the same identity/session and a previously loaded membership across demotion.
            async with sessions() as db:
                async with db.begin():
                    loaded = await db.get(Membership, (owner.tenant_id, admin.person_id))
                    assert loaded.role == "admin"
                    await organisation_acquisition_activity(ownership(db, admin.actor), admin.actor)
                async with sessions() as writer, writer.begin():
                    await writer.execute(
                        update(Membership)
                        .where(
                            Membership.tenant_id == owner.tenant_id,
                            Membership.person_id == admin.person_id,
                        )
                        .values(role="member")
                    )
                assert loaded.role == "admin"
                async with db.begin():
                    with pytest.raises(ConversationDenied):
                        await organisation_acquisition_activity(
                            ownership(db, admin.actor), admin.actor
                        )
                    assert loaded.role == "member"
        finally:
            await engine.dispose()

    run(exercise())


def account_empty_body():
    return dict(
        timezone="Asia/Kolkata",
        days=[
            dict(date=(FIRST + timedelta(days=i)).isoformat(), analysed=0, analysed_seconds=0)
            for i in range(30)
        ],
        analysed_last_30_days=0,
        analysed_previous_30_days=0,
    )
