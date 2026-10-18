"""A call uses minutes only when its report succeeds (owner decision, 17 Oct 2026)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.billing.ledger import BillingLedger
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement,
    ConversationReportMinuteEvent,
)
from ac_platform.conversation_intelligence.admission_lock import take_admission_lock
from ac_platform.organisations.usage import member_usage
from tests.database.test_billing_ledger_postgresql import raw_usage
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


def _event(usage_id: UUID, revision: int, kind: str, seconds: int) -> ConversationReportMinuteEvent:
    return ConversationReportMinuteEvent(
        usage_id=usage_id,
        revision=revision,
        key=f"{kind}:{revision}",
        kind=kind,
        seconds=seconds,
        receipt_sha256="c" * 64,
        created_at=NOW,
    )


def test_released_calls_use_nothing_and_every_other_call_still_counts(postgres_harness):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            owner = await seed(engine)
            async with sessions() as db, db.begin():
                # Failed before a report: released, so it uses nothing.
                failed = await raw_usage(db, owner, 600, at=NOW)
                db.add_all([_event(failed, 1, "reserved", 600), _event(failed, 2, "released", 0)])
                # Retried after a release: holds its seconds again until it finishes.
                retried = await raw_usage(db, owner, 300, at=NOW)
                db.add_all(
                    [
                        _event(retried, 1, "reserved", 300),
                        _event(retried, 2, "released", 0),
                        _event(retried, 3, "reserved", 300),
                    ]
                )
                # Still running: holds its seconds, so parallel uploads cannot overspend.
                running = await raw_usage(db, owner, 120, at=NOW)
                db.add(_event(running, 1, "reserved", 120))
                # Older call with no minute events: unchanged, still holds.
                legacy = await raw_usage(db, owner, 60, at=NOW)
                # Report delivered and settled: charged.
                done = await raw_usage(db, owner, 240, at=NOW)
                db.add(_event(done, 1, "reserved", 240))
                await db.flush()
                await take_admission_lock(db, owner.tenant_id)
                db.add(
                    ConversationAcquisitionSettlement(
                        usage_id=done,
                        charged_seconds=240,
                        kind="completed",
                        receipt_sha256="b" * 64,
                        created_at=NOW,
                    )
                )
            async with sessions() as db:
                uses = {
                    use.use_id: (use.seconds, use.pending)
                    for use in await BillingLedger(db).person_uses(
                        tenant_id=owner.tenant_id, person_id=owner.person_id
                    )
                }
                assert uses[str(failed)] == (0, False)
                assert uses[str(retried)] == (300, True)
                assert uses[str(running)] == (120, True)
                assert uses[str(legacy)] == (60, True)
                assert uses[str(done)] == (240, False)
                seconds, calls, _ = (
                    await member_usage(db, owner.tenant_id, NOW - timedelta(days=1))
                )[owner.person_id]
                assert (seconds, calls) == (300 + 120 + 60 + 240, 5)
        finally:
            await engine.dispose()

    run(exercise())
