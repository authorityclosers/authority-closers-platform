"""Disposable PostgreSQL credit history: exact totals, audit atomicity and scope.

The established harness applies the migration chain in a new loopback schema;
missing database configuration fails rather than skipping this evidence.
"""

import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal, localcontext
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.audit.models import AuditChainHead, AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.billing import credits
from ac_platform.billing.credit_models import BillingCreditEntry
from ac_platform.billing.credits import CREDIT_APPEND_ACTION, CreditsLedger
from ac_platform.billing.ledger import BillingConflict, BillingError, BillingLedger
from ac_platform.billing.models import BillingLedgerEntry
from ac_platform.db.models import model_metadata
from tests.database.test_conversation_postgresql import ROOT, run, seed, wait_blocked
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


@asynccontextmanager
async def lab(postgres_harness):
    engine = create_async_engine(postgres_harness.url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        owner = await seed(engine)
        colleague = await seed(engine, tenant_id=owner.tenant_id)
        organisation = await seed(engine, role="owner")
        async with sessions() as database, database.begin():
            ledger = BillingLedger(database)
            personal = await ledger.personal_account(
                tenant_id=owner.tenant_id, person_id=owner.person_id, create=True
            )
            other_personal = await ledger.personal_account(
                tenant_id=colleague.tenant_id, person_id=colleague.person_id, create=True
            )
            pooled = await ledger.organisation_account(
                tenant_id=organisation.tenant_id, create=True
            )
        yield SimpleNamespace(
            engine=engine,
            sessions=sessions,
            owner=owner,
            colleague=colleague,
            organisation=organisation,
            personal=personal,
            other_personal=other_personal,
            pooled=pooled,
        )
    finally:
        await engine.dispose()


async def append(database, account, quantity=Decimal("1.25"), **changes):
    facts = dict(
        tenant_id=account.tenant_id,
        account_id=account.id,
        quantity=quantity,
        source_ref=f"fictional:{uuid4()}",
        actor_type="system",
        reason="Synthetic quantity",
    )
    facts.update(changes)
    return await CreditsLedger(database).append(**facts)


def test_exact_totals_are_independent_of_minutes_and_access(postgres_harness):
    async def exercise():
        async with lab(postgres_harness) as state, state.sessions() as database, database.begin():
            account = state.personal
            ledger = CreditsLedger(database)
            scope = dict(tenant_id=account.tenant_id, account_id=account.id)
            assert await ledger.history(**scope) == []
            assert await ledger.balance(**scope) == Decimal(0)
            minutes = BillingLedger(database)
            before = await minutes.project_person(
                tenant_id=state.owner.tenant_id,
                person_id=state.owner.person_id,
                now=state.owner.now,
            )
            await append(
                database,
                account,
                Decimal("123456789012345678901234567890.12345678901234567890123456789"),
            )
            await append(database, account, Decimal("0.00000000000000000000000000001"))
            await append(database, account, Decimal("-123456789012345678901234567890"))
            with localcontext() as context:
                context.prec = 2
                assert await ledger.balance(**scope) == Decimal("0.12345678901234567890123456790")
            assert len(await ledger.history(**scope)) == 3
            after = await minutes.project_person(
                tenant_id=state.owner.tenant_id,
                person_id=state.owner.person_id,
                now=state.owner.now,
            )
            assert after.available_seconds == before.available_seconds
            assert after.plan_key == before.plan_key
            assert after.per_call_seconds == before.per_call_seconds
            assert (
                await database.scalar(
                    select(func.count())
                    .select_from(BillingLedgerEntry)
                    .where(BillingLedgerEntry.account_id == account.id)
                )
                == 0
            )

    run(exercise())


def test_personal_and_organisation_scope_and_corrections(postgres_harness):
    async def exercise():
        async with lab(postgres_harness) as state, state.sessions() as database, database.begin():
            ledger = CreditsLedger(database)
            original = await append(database, state.personal, Decimal("2.50"))
            await append(database, state.other_personal, Decimal("9.75"))
            pooled = await append(database, state.pooled, Decimal("50.125"))
            correction = await append(
                database,
                state.personal,
                Decimal("-0.25"),
                corrected_entry_id=original.id,
                actor_type="person",
                actor_person_id=state.owner.person_id,
                reason="Correct synthetic evidence",
            )
            scope = dict(tenant_id=state.personal.tenant_id, account_id=state.personal.id)
            assert await ledger.balance(**scope) == Decimal("2.25")
            assert {e.id for e in await ledger.history(**scope)} == {original.id, correction.id}
            assert original.quantity == Decimal("2.50")
            assert correction.corrected_entry_id == original.id
            assert await ledger.balance(
                tenant_id=state.pooled.tenant_id, account_id=state.pooled.id
            ) == Decimal("50.125")
            assert (
                await ledger.history(tenant_id=state.pooled.tenant_id, account_id=state.personal.id)
                == []
            )
            assert (
                await ledger.balance(tenant_id=state.pooled.tenant_id, account_id=state.personal.id)
                == 0
            )
            with pytest.raises(BillingError, match="outside this tenant"):
                await append(database, state.personal, tenant_id=state.pooled.tenant_id)
            for wrong_id in (pooled.id, uuid4()):
                with pytest.raises(BillingError, match="this account's"):
                    await append(database, state.personal, corrected_entry_id=wrong_id)
            audit = await database.get(AuditEvent, correction.audit_event_id)
            assert audit.action == CREDIT_APPEND_ACTION
            assert audit.tenant_id == state.personal.tenant_id
            assert audit.actor_person_id == state.owner.person_id
            assert audit.payload["corrected_entry_id"] == str(original.id)
            assert len(await AuditRepository(database).reconstruct(state.personal.tenant_id)) == 3

    run(exercise())


def test_retry_and_conflicting_source_facts(postgres_harness):
    async def exercise():
        async with lab(postgres_harness) as state:
            source = f"fictional:{uuid4()}"
            async with state.sessions() as database, database.begin():
                first = await append(database, state.personal, source_ref=source)
            async with state.sessions() as database, database.begin():
                assert (await append(database, state.personal, source_ref=source)).id == first.id
                for changes in (
                    dict(quantity=Decimal("2.25")),
                    dict(reason="Different reason"),
                    dict(actor_type="person", actor_person_id=state.owner.person_id),
                    dict(corrected_entry_id=first.id),
                ):
                    with pytest.raises(BillingConflict):
                        await append(database, state.personal, source_ref=source, **changes)
                with pytest.raises(BillingConflict):
                    await append(database, state.pooled, source_ref=source)
                assert (
                    len(await AuditRepository(database).reconstruct(state.personal.tenant_id)) == 1
                )
                assert await CreditsLedger(database).balance(
                    tenant_id=state.personal.tenant_id, account_id=state.personal.id
                ) == Decimal("1.25")

    run(exercise())


def test_failed_audit_and_failed_credit_flush_roll_back_together(postgres_harness, monkeypatch):
    real_append = credits.append_audit_event

    async def fail_after_audit(*args, **kwargs):
        await real_append(*args, **kwargs)
        raise RuntimeError("Synthetic audit failure")

    async def exercise():
        async with lab(postgres_harness) as state:
            async with state.sessions() as database, database.begin():
                with monkeypatch.context() as patch:
                    patch.setattr(credits, "append_audit_event", fail_after_audit)
                    with pytest.raises(RuntimeError, match="Synthetic audit failure"):
                        await append(database, state.personal)
                # A nonexistent system actor fails after audit and must leave no audit/head.
                with pytest.raises(IntegrityError):
                    await append(database, state.personal, actor_person_id=uuid4())
                real_flush = database.flush

                async def fail_credit_flush(*args, **kwargs):
                    if any(isinstance(row, BillingCreditEntry) for row in database.new):
                        raise RuntimeError("Synthetic credit flush failure")
                    await real_flush(*args, **kwargs)

                with monkeypatch.context() as patch:
                    patch.setattr(database, "flush", fail_credit_flush)
                    with pytest.raises(RuntimeError, match="Synthetic credit flush failure"):
                        await append(database, state.personal)
            # The caller committed despite catching both failures.
            async with state.sessions() as database:
                assert (
                    await CreditsLedger(database).history(
                        tenant_id=state.personal.tenant_id, account_id=state.personal.id
                    )
                    == []
                )
                for model in (AuditEvent, AuditChainHead):
                    assert (
                        await database.scalar(
                            select(func.count())
                            .select_from(model)
                            .where(model.tenant_id == state.personal.tenant_id)
                        )
                        == 0
                    )

    run(exercise())


def test_database_refuses_mutation_and_cross_scope_evidence(postgres_harness):
    async def exercise():
        async with lab(postgres_harness) as state:
            async with state.sessions() as database, database.begin():
                original = await append(database, state.personal)
            for command in (
                update(BillingCreditEntry)
                .where(BillingCreditEntry.id == original.id)
                .values(quantity=Decimal("20")),
                delete(BillingCreditEntry).where(BillingCreditEntry.id == original.id),
            ):
                with pytest.raises(DBAPIError, match="append-only"):
                    async with state.sessions() as database, database.begin():
                        await database.execute(command)
            # Reusing an audit for another row is refused even through raw INSERT.
            raw = {
                column.name: getattr(original, column.name)
                for column in BillingCreditEntry.__table__.columns
            }
            raw.update(id=uuid4(), source_ref=f"fictional:{uuid4()}")
            with pytest.raises(DBAPIError, match="audit scope"):
                async with state.sessions() as database, database.begin():
                    await database.execute(insert(BillingCreditEntry).values(**raw))
            async with state.sessions() as database:
                preserved = await database.get(BillingCreditEntry, original.id)
                assert preserved.quantity == original.quantity

    run(exercise())


def test_concurrent_retry_waits_for_account_lock_and_counts_once(postgres_harness):
    async def exercise():
        async with lab(postgres_harness) as state:
            source = f"fictional:{uuid4()}"
            ready = asyncio.get_running_loop().create_future()
            async with state.sessions() as first, first.begin():
                original = await append(first, state.personal, source_ref=source)

                async def retry():
                    async with state.sessions() as second, second.begin():
                        ready.set_result(await second.scalar(text("SELECT pg_backend_pid()")))
                        return await append(second, state.personal, source_ref=source)

                task = asyncio.create_task(retry())
                try:
                    await wait_blocked(state.engine, await ready, task)
                    await first.commit()
                    replay = await asyncio.wait_for(task, timeout=10)
                    assert replay.id == original.id
                finally:
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
            async with state.sessions() as database:
                assert await CreditsLedger(database).balance(
                    tenant_id=state.personal.tenant_id, account_id=state.personal.id
                ) == Decimal("1.25")
                assert (
                    len(await AuditRepository(database).reconstruct(state.personal.tenant_id)) == 1
                )

    run(exercise())


def test_racing_source_reuse_in_different_tenants_preserves_only_winning_audit(
    postgres_harness, monkeypatch
):
    real_append = credits.append_audit_event
    barrier = None

    async def synchronise_audit(*args, **kwargs):
        await barrier.wait()
        return await real_append(*args, **kwargs)

    async def exercise():
        nonlocal barrier
        barrier = asyncio.Barrier(2)
        async with lab(postgres_harness) as state:
            source = f"fictional:{uuid4()}"

            async def write(account):
                async with state.sessions() as database, database.begin():
                    return await append(database, account, source_ref=source)

            with monkeypatch.context() as patch:
                patch.setattr(credits, "append_audit_event", synchronise_audit)
                results = await asyncio.wait_for(
                    asyncio.gather(
                        write(state.personal), write(state.pooled), return_exceptions=True
                    ),
                    timeout=15,
                )
            assert sum(isinstance(result, BillingConflict) for result in results) == 1
            assert sum(isinstance(result, BillingCreditEntry) for result in results) == 1
            async with state.sessions() as database:
                entries = list(
                    await database.scalars(
                        select(BillingCreditEntry).where(BillingCreditEntry.source_ref == source)
                    )
                )
                assert len(entries) == 1
                audits = list(
                    await database.scalars(
                        select(AuditEvent).where(
                            AuditEvent.tenant_id.in_(
                                [state.personal.tenant_id, state.pooled.tenant_id]
                            )
                        )
                    )
                )
                assert len(audits) == 1
                assert audits[0].id == entries[0].audit_event_id

    run(exercise())


def test_fresh_migration_and_registered_unscaled_numeric(postgres_harness):
    config = Config(str(ROOT / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    head = scripts.get_current_head()
    assert "20261003_0073" in {
        revision.revision for revision in scripts.iterate_revisions(head, "base")
    }
    table = model_metadata().tables["billing_credit_entries"]
    assert table.c.quantity.type.precision is None and table.c.quantity.type.scale is None
    with postgres_harness.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == head
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM pg_trigger WHERE tgrelid = "
                    "'billing_credit_entries'::regclass AND NOT tgisinternal"
                )
            )
            == 2
        )
    migration = (ROOT / "db/migrations/versions/20261003_0073_credits_ledger.py").read_text()
    assert "raise RuntimeError" in migration.split("def downgrade() -> None:")[1]
