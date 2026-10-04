"""AUT-954: fictional members share one ledger pool under the tenant admission lock."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import event, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.settings import Settings
from ac_platform.audit.service import AuditRepository
from ac_platform.billing.ledger import LEGACY_GRANT_PREFIX, BillingError
from ac_platform.billing.models import BillingAccount
from ac_platform.conversation_intelligence.acquisition_challenge import UploadChallenge
from ac_platform.conversation_intelligence.acquisition_models import ConversationAcquisitionUsage
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.acquisition_usage import (
    TRIAL_ALLOWANCE_INSUFFICIENT_MESSAGE,
)
from ac_platform.conversation_intelligence.application import ConversationDenied
from ac_platform.conversation_intelligence.entitlements import MinuteGrant
from ac_platform.conversation_intelligence.minute_account_admin import (
    MINUTE_GRANT_ACTION,
    MINUTE_GRANT_RESOURCE_TYPE,
    append_minute_grant,
)
from ac_platform.conversation_intelligence.sales_xray_tenants import SALES_XRAY_MEMBER_ROLES
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.conversation_acquisition import install_acquisition_http
from ac_platform.http.operations import install_operations_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.organisations.usage import organisation_pool
from ac_platform.tenancy.models import Membership
from tests.database.test_billing_ledger_postgresql import Operations, bootstrap_operations, source
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


def acquisition(database, member, operations):
    return AcquisitionSessions(
        database,
        tenant_id=member.tenant_id,
        operations_tenant_id=operations.tenant_id,
        policy_revision="fictional-org-pool-v1",
        trial_enabled=False,
    )


async def fixtures(engine):
    first = await seed(engine, role="member")
    second = await seed(engine, tenant_id=first.tenant_id, role="member")
    operations = await seed(engine, role="owner")
    return first, second, operations


async def grant(database, member, operations, seconds, *, personal=False, **kwargs):
    ledger = acquisition(database, member, operations).ledger
    account = (
        await ledger.personal_account(
            tenant_id=member.tenant_id, person_id=member.person_id, create=True
        )
        if personal
        else await ledger.organisation_account(tenant_id=member.tenant_id, create=True)
    )
    return await ledger.write_lot(
        account=account,
        kind=kwargs.pop("kind", "grant"),
        seconds=seconds,
        valid_from=datetime.now(UTC) - timedelta(minutes=1),
        source_ref=f"fictional-grant:{uuid4()}",
        actor_type="system",
        **kwargs,
    )


@pytest.mark.parametrize("member_grant", [False, True])
def test_two_members_share_600_seconds_and_keep_usage_attribution(postgres_harness, member_grant):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            first, second, operations = await fixtures(engine)
            async with AsyncSession(engine) as db, db.begin():
                await grant(db, first, operations, 600, personal=member_grant)
                for member in (first, second):
                    assert await acquisition(db, member, operations).allowance(
                        actor=member.actor
                    ) == {
                        "allowance_seconds": 600,
                        "committed_seconds": 0,
                        "available_seconds": 600,
                    }
                measured = source(600)
                app = acquisition(db, first, operations)
                usage_id = await app.reserve(measured, actor=first.actor)
                assert await app.reserve(measured, actor=first.actor) == usage_id
                await app.settle(usage_id, charged_seconds=600, receipt_sha256="a" * 64)
            async with AsyncSession(engine) as db, db.begin():
                for member in (first, second):
                    assert (
                        await acquisition(db, member, operations).allowance(actor=member.actor)
                    )["available_seconds"] == 0
                with pytest.raises(ConversationDenied, match=TRIAL_ALLOWANCE_INSUFFICIENT_MESSAGE):
                    await acquisition(db, second, operations).reserve(source(1), actor=second.actor)
                usage = await db.get(ConversationAcquisitionUsage, usage_id)
                assert usage.person_id == first.person_id and usage.tenant_id == first.tenant_id
                assert await organisation_pool(db, first.tenant_id) == {
                    "available_seconds": 0,
                    "balance_seconds": 0,
                    "used_seconds": 600,
                }
        finally:
            await engine.dispose()

    run(exercise())


def test_concurrent_members_cannot_overdraw_and_no_work_releases_the_pool(postgres_harness):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            first, second, operations = await fixtures(engine)
            async with AsyncSession(engine) as db, db.begin():
                await grant(db, first, operations, 600)
            ready = asyncio.Event()

            async def reserve(member):
                async with AsyncSession(engine) as db, db.begin():
                    await ready.wait()
                    return await acquisition(db, member, operations).reserve(
                        source(400), actor=member.actor
                    )

            tasks = [asyncio.create_task(reserve(member)) for member in (first, second)]
            ready.set()
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True), timeout=15
            )
            denied = [item for item in results if isinstance(item, ConversationDenied)]
            assert len(denied) == 1 and str(denied[0]) == TRIAL_ALLOWANCE_INSUFFICIENT_MESSAGE
            winner = results[1] if isinstance(results[0], ConversationDenied) else results[0]
            async with AsyncSession(engine) as db, db.begin():
                app = acquisition(db, second, operations)
                assert (await app.allowance(actor=second.actor))["available_seconds"] == 200
                await app.settle(winner, charged_seconds=0, receipt_sha256="b" * 64, no_work=True)
                assert (await app.allowance(actor=second.actor))["available_seconds"] == 600
                await app.reserve(source(600), actor=second.actor)
        finally:
            await engine.dispose()

    run(exercise())


def test_empty_org_has_no_trial_and_operations_and_inactive_members_are_refused(postgres_harness):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            first, second, operations = await fixtures(engine)
            async with AsyncSession(engine) as db, db.begin():
                for member in (first, second):
                    app = acquisition(db, member, operations)
                    assert await app.allowance(actor=member.actor) == {
                        "allowance_seconds": 0,
                        "committed_seconds": 0,
                        "available_seconds": 0,
                    }
                    with pytest.raises(ConversationDenied):
                        await app.reserve(source(1), actor=member.actor)
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(BillingAccount)
                        .where(BillingAccount.tenant_id == first.tenant_id)
                    )
                    == 0
                )
                await grant(db, first, operations, 600)
                with pytest.raises(ConversationDenied):
                    await acquisition(db, first, operations).reserve(
                        source(1), actor=operations.actor
                    )
                with pytest.raises(BillingError, match="operations tenant"):
                    await acquisition(db, operations, operations).allowance(actor=operations.actor)
                await db.execute(
                    update(Membership)
                    .where(
                        Membership.tenant_id == first.tenant_id,
                        Membership.person_id == second.person_id,
                    )
                    .values(status="inactive", ended_at=datetime.now(UTC))
                )
                with pytest.raises(ConversationDenied):
                    await acquisition(db, second, operations).reserve(source(1), actor=second.actor)
        finally:
            await engine.dispose()

    run(exercise())


def test_org_plan_cap_expiry_closings_and_other_tenant_isolation(postgres_harness):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            first, second, operations = await fixtures(engine)
            foreign = await seed(engine)
            async with AsyncSession(engine) as db, db.begin():
                await grant(db, foreign, operations, 100_000)
                lot = await grant(
                    db,
                    first,
                    operations,
                    15_000,
                    kind="period_grant",
                    plan_key="organisation",
                    expires_at=datetime.now(UTC) + timedelta(days=30),
                )
                ledger = acquisition(db, second, operations).ledger
                await ledger.write_closing(
                    lot=lot,
                    kind="correction",
                    seconds=600,
                    remainder=15_000,
                    source_ref=f"fictional-close:{uuid4()}",
                    actor_type="system",
                )
                await grant(
                    db,
                    first,
                    operations,
                    600,
                    personal=True,
                    expires_at=datetime.now(UTC) - timedelta(seconds=1),
                )
                projected = await ledger.project_organisation(
                    tenant_id=first.tenant_id, now=datetime.now(UTC)
                )
                assert projected.trial is None and projected.plan_key == "organisation"
                assert projected.available_seconds == 14_400
                assert projected.per_call_seconds == 7_200
                app = acquisition(db, second, operations)
                # The measured-source receipt has its own 6000 s bound; the pool
                # still projects the organisation plan's 7200 s billing cap.
                await app.reserve(source(6_000), actor=second.actor)
                assert (await app.allowance(actor=second.actor))["available_seconds"] == 8_400
        finally:
            await engine.dispose()

    run(exercise())


async def legacy_grant(database, member, operations):
    grant_id, audit_id = uuid4(), uuid4()
    reason = "Fictional organisation legacy grant"
    await append_minute_grant(
        database,
        tenant_id=member.tenant_id,
        person_id=member.person_id,
        operations_tenant_id=operations.tenant_id,
        roles=SALES_XRAY_MEMBER_ROLES,
        grant=MinuteGrant(
            str(member.tenant_id),
            str(member.person_id),
            str(grant_id),
            600,
            f"audit-event:{audit_id}",
            str(operations.person_id),
            reason,
        ),
    )
    await AuditRepository(database).append(
        event_id=audit_id,
        tenant_id=operations.tenant_id,
        actor_person_id=operations.person_id,
        session_id=operations.session_id,
        action=MINUTE_GRANT_ACTION,
        resource_type=MINUTE_GRANT_RESOURCE_TYPE,
        resource_id=grant_id,
        reason=reason,
        payload={
            "idempotency_key": str(uuid4()),
            "request_digest": "c" * 64,
            "grant_id": str(grant_id),
            "tenant_id": str(member.tenant_id),
            "person_id": str(member.person_id),
            "minutes": 10,
            "seconds": 600,
        },
    )
    return audit_id


def test_legacy_grant_from_another_member_is_read_only_then_mirrored_once(postgres_harness):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            first, second, operations = await fixtures(engine)
            async with AsyncSession(engine) as db, db.begin():
                audit_id = await legacy_grant(db, first, operations)
                app = acquisition(db, second, operations)
                expected = {
                    "allowance_seconds": 600,
                    "committed_seconds": 0,
                    "available_seconds": 600,
                }
                assert await app.allowance(actor=second.actor) == expected
                assert not db.new
                measured = source(120)
                usage_id = await app.reserve(measured, actor=second.actor)
                assert await app.reserve(measured, actor=second.actor) == usage_id
                await app.reserve(source(60), actor=second.actor)
                assert await app.allowance(actor=first.actor) == {
                    "allowance_seconds": 600,
                    "committed_seconds": 180,
                    "available_seconds": 420,
                }
                entries = await app.ledger.organisation_entries(tenant_id=first.tenant_id)
                assert (
                    len(entries) == 1
                    and entries[0].source_ref == f"{LEGACY_GRANT_PREFIX}{audit_id}"
                )
                account = await db.get(BillingAccount, entries[0].account_id)
                assert account.person_id == first.person_id
        finally:
            await engine.dispose()

    run(exercise())


def test_session_usage_and_admin_share_pool_and_keep_personal_call_history(
    postgres_harness, record_property
):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            first, second, operations = await fixtures(engine)
            public = await seed(engine)
            ops = Operations(operations.tenant_id, operations.person_id, operations.session_id)
            await bootstrap_operations(sessions, ops)
            async with sessions() as db, db.begin():
                await grant(db, first, operations, 600)
                await grant(db, first, operations, 60, personal=True)
                await acquisition(db, first, operations).reserve(source(120), actor=first.actor)
            settings = Settings(
                _env_file=None,
                environment="test",
                public_app_url="https://learner.example.test",
                admin_app_url="https://admin.example.test",
                coach_app_url="https://coach.example.test",
                api_url="https://api.example.test",
                sales_xray_app_url="https://salesxray.example.test",
                operations_tenant_id=operations.tenant_id,
                public_learner_tenant_id=public.tenant_id,
            )
            intake = SimpleNamespace(
                policy=SimpleNamespace(tenant_ids={first.tenant_id, public.tenant_id})
            )

            async def require_actor(request: Request):
                actor = (
                    ops.manager if request.url.hostname == "admin.example.test" else second.actor
                )
                async with sessions() as db, db.begin():
                    yield AuthenticatedTransaction(
                        db, None, SimpleNamespace(actor=actor), "fictional-session"
                    )

            def factory(db, tenant_id):
                return AcquisitionSessions(
                    db,
                    tenant_id=tenant_id,
                    operations_tenant_id=operations.tenant_id,
                    policy_revision="fictional-org-pool-v1",
                    trial_enabled=tenant_id == public.tenant_id,
                )

            app = FastAPI()
            register_problem_handlers(app)
            install_acquisition_http(
                app,
                settings=settings,
                sessions=sessions,
                require_actor=require_actor,
                factory=factory,
                challenge=UploadChallenge(
                    secret=settings.session_token_pepper, hostname="salesxray.example.test"
                ),
                intake=intake,
            )
            install_operations_http(
                app,
                settings=settings,
                sessions=sessions,
                require_actor=require_actor,
                intake=intake,
            )
            statements = []

            def capture(conn, cursor, statement, parameters, context, executemany):
                statements.append(statement)

            event.listen(engine.sync_engine, "before_cursor_execute", capture)
            try:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="https://salesxray.example.test",
                ) as client:
                    client.cookies.set(settings.session_cookie_name, "s" * 43)
                    session = await client.get("/v1/conversation/acquisition/session")
                    usage = await client.get("/v1/me/usage")
                    admin = await client.get(
                        f"https://admin.example.test/v1/admin/conversation-minute-accounts/{first.tenant_id}/{second.person_id}"
                    )
                    assert session.status_code == usage.status_code == admin.status_code == 200
                    expected = {
                        "allowance_seconds": 660,
                        "committed_seconds": 120,
                        "available_seconds": 540,
                    }
                    assert session.json() == {"state": "account", "allowance": expected}
                    assert usage.json() == {
                        "allowance": expected,
                        "calls": [],
                        "earlier_seconds": 0,
                        "truncated": False,
                    }
                    assert {
                        key: admin.json()[f"shared_upload_{key}"] for key in expected
                    } == expected
                    record_property("org_session", json.dumps(session.json()))
                    record_property("org_usage", json.dumps(usage.json()))
                    record_property("org_admin", json.dumps(admin.json()))
            finally:
                event.remove(engine.sync_engine, "before_cursor_execute", capture)
            assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
        finally:
            await engine.dispose()

    run(exercise())
