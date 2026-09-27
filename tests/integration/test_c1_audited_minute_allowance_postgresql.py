"""PostgreSQL proof that audited admin minutes extend shared upload/C1 use once."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.audit.models import AuditEvent
from ac_platform.authorization.application import CapabilityApplication
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage,
)
from ac_platform.conversation_intelligence.acquisition_sessions import (
    AcquisitionSessions,
    MeasuredSource,
)
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationDenied,
)
from ac_platform.conversation_intelligence.entitlements import (
    BudgetAccount,
    MinuteAccount,
    MinuteGrant,
    grant_minutes,
)
from ac_platform.conversation_intelligence.minute_account_admin import MINUTE_GRANT_ACTION
from ac_platform.conversation_intelligence.models import (
    ConversationBudgetAccount,
    ConversationMinuteAccount,
)
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.operations import (
    MAX_MINUTE_GRANT_MINUTES,
    MAX_SAFE_JSON_INTEGER,
    ConversationMinuteGrantRequest,
    install_operations_http,
)
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from tests.database.test_conversation_postgresql import seed, seed_budget, seed_run_intent
from tests.integration.test_operations_http_postgresql import (
    _Harness,
    _run_async,
    _settings,
)
from tests.integration.test_operations_http_postgresql import (
    _seed as seed_operations,
)
from tests.integration.test_operations_http_postgresql import (
    postgres_harness as operations_postgres_harness,
)


@pytest.fixture(scope="function")
def postgres_harness() -> Iterator[_Harness]:
    yield from operations_postgres_harness.__wrapped__()


def source(seconds: int) -> MeasuredSource:
    return MeasuredSource(uuid4(), uuid4().hex * 2, seconds * 1000, uuid4().hex * 2)


def test_admin_grant_request_uses_exact_json_seconds_range() -> None:
    request = ConversationMinuteGrantRequest(
        minutes=MAX_MINUTE_GRANT_MINUTES,
        reason="The API safe-integer boundary",
    )
    assert request.minutes * 60 + 3_600 <= MAX_SAFE_JSON_INTEGER
    with pytest.raises(ValidationError):
        ConversationMinuteGrantRequest(
            minutes=MAX_MINUTE_GRANT_MINUTES + 1,
            reason="Beyond the API safe-integer boundary",
        )


class _AllowanceAuthority:
    """Narrow local seam for C1's trusted operations-tenant provenance."""

    def __init__(self, operations_tenant_id: UUID) -> None:
        self.operations_tenant_id = operations_tenant_id

    async def admit(self, _app: ConversationApplication, _actor: ActorContext) -> object:
        return object()

    async def reconcile_existing_minute_account(
        self, _app: ConversationApplication, _actor: ActorContext, *, bundle: object
    ) -> None:
        assert bundle is not None


def _manager_app(
    *,
    sessions: async_sessionmaker[AsyncSession],
    actor: ActorContext,
    operations_tenant_id: UUID,
    tester_policy: Any = None,
) -> FastAPI:
    async def require_actor(_request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        async with sessions() as database, database.begin():
            yield AuthenticatedTransaction(
                database=database,
                identity=cast(Any, object()),
                resolved=ResolvedActorContext(
                    actor=actor,
                    membership_role="owner",
                    person_revision=0,
                    session_revision=0,
                    tenant_revision=0,
                    membership_revision=0,
                ),
                token=str(uuid4()),
            )

    application = FastAPI()
    register_problem_handlers(application)
    install_operations_http(
        application,
        settings=_settings(operations_tenant_id=operations_tenant_id),
        sessions=sessions,
        require_actor=require_actor,
        tester_policy=cast(Any, tester_policy),
    )
    return application


class _CurrentAccountMinutePolicy:
    async def for_learner_account(
        self,
        _database: AsyncSession,
        *,
        tenant_id: UUID,
        person_id: UUID,
    ) -> object:
        assert tenant_id
        assert person_id
        return object()


def test_admin_minutes_extend_claimed_guest_usage_and_c1_once_through_exact_cap(
    postgres_harness: _Harness,
) -> None:
    operations = seed_operations(postgres_harness.engine)

    async def scenario() -> None:
        async_engine = create_async_engine(
            postgres_harness.schema_url,
            connect_args={"connect_timeout": 5},
            pool_pre_ping=True,
        )
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        try:
            learner = await seed(async_engine)
            budget_scope = await seed_budget(async_engine)
            first_run = await seed_run_intent(
                async_engine,
                learner,
                budget_scope,
                allowance_seconds=3_600,
            )
            manager = ActorContext(
                person_id=operations.person_id,
                session_id=operations.session_id,
                tenant_id=operations.tenant_id,
                permissions=frozenset({"admin_surface"}),
            )
            # The shared operations fixture uses a historical fixed timestamp;
            # give this synthetic request a current named session.
            async with sessions() as database, database.begin():
                await database.execute(
                    update(IdentitySession)
                    .where(IdentitySession.id == operations.session_id)
                    .values(expires_at=datetime.now(UTC) + timedelta(days=1))
                )
            async with sessions() as database, database.begin():
                await CapabilityApplication(
                    database,
                    operations_tenant_id=operations.tenant_id,
                ).bootstrap_first_manager(
                    person_id=operations.person_id,
                    command_id=uuid4(),
                    reason="Disposable C1 allowance integration fixture",
                )

            app = _manager_app(
                sessions=sessions,
                actor=manager,
                operations_tenant_id=operations.tenant_id,
            )
            target = (
                f"/v1/admin/conversation-minute-accounts/"
                f"{learner.tenant_id}/{learner.person_id}/grants"
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://admin.authorityclosers.test",
            ) as client:
                response = await client.post(
                    target,
                    json={"minutes": 100, "reason": "Approved finite learner allowance"},
                    headers={
                        "Origin": "https://admin.authorityclosers.test",
                        "Idempotency-Key": "c1-audited-add-on-100m",
                    },
                )
            assert response.status_code == 200, response.text
            assert response.json()["account"]["shared_upload_allowance_seconds"] == 9_600

            authority = _AllowanceAuthority(operations.tenant_id)
            async with sessions() as database, database.begin():
                acquisition = AcquisitionSessions(
                    database,
                    tenant_id=learner.tenant_id,
                    policy_revision="c1-audited-add-on-test-v1",
                    operations_tenant_id=operations.tenant_id,
                )
                visitor = await acquisition.issue()
                await acquisition.reserve(source(3_500), token=visitor.token)
                await acquisition.claim(visitor.token, learner.actor)
                await acquisition.reserve(source(3_000), actor=learner.actor)
                await acquisition.reserve(source(2_980), actor=learner.actor)
                assert (await acquisition.allowance(actor=learner.actor))[
                    "committed_seconds"
                ] == 9_480

                await ConversationApplication(database, clock=lambda: learner.now).request_run(
                    learner.actor,
                    first_run,
                    key="c1-at-exact-audited-cap",
                    authority=cast(Any, authority),
                )
                allowance = await acquisition.allowance(actor=learner.actor)
                assert allowance["allowance_seconds"] == 9_600
                assert allowance["committed_seconds"] == 9_600
                assert allowance["available_seconds"] == 0

                usage_rows = (
                    await database.scalars(
                        select(ConversationAcquisitionUsage).where(
                            ConversationAcquisitionUsage.tenant_id == learner.tenant_id,
                            ConversationAcquisitionUsage.person_id == learner.person_id,
                        )
                    )
                ).all()
                assert sum(row.reserved_seconds for row in usage_rows) == 5_980
                visitor_rows = (
                    await database.scalars(
                        select(ConversationAcquisitionUsage).where(
                            ConversationAcquisitionUsage.tenant_id == learner.tenant_id,
                            ConversationAcquisitionUsage.visitor_id == visitor.visitor_id,
                        )
                    )
                ).all()
                assert sum(row.reserved_seconds for row in visitor_rows) == 3_500

                minute_row = await database.scalar(
                    select(ConversationMinuteAccount).where(
                        ConversationMinuteAccount.tenant_id == learner.tenant_id,
                        ConversationMinuteAccount.person_id == learner.person_id,
                    )
                )
                assert minute_row is not None
                minute_account = MinuteAccount.from_dict(minute_row.snapshot)
                assert sum(item.committed_seconds for item in minute_account.reservations) == 120
                assert minute_account.available_seconds == 9_480

                budget_row = await database.get(ConversationBudgetAccount, budget_scope)
                assert budget_row is not None
                assert budget_row.snapshot["cap_paise"] == 150_000
                assert BudgetAccount.from_dict(budget_row.snapshot).available_paise == 150_000

            next_run = await seed_run_intent(
                async_engine,
                learner,
                budget_scope,
                allowance_seconds=3_600,
                add_allowance=False,
            )
            async with sessions() as database, database.begin():
                acquisition = AcquisitionSessions(
                    database,
                    tenant_id=learner.tenant_id,
                    policy_revision="c1-audited-add-on-test-v1",
                    operations_tenant_id=operations.tenant_id,
                )
                with pytest.raises(ConversationDenied, match="remaining trial minutes"):
                    await ConversationApplication(database, clock=lambda: learner.now).request_run(
                        learner.actor,
                        next_run,
                        key="c1-over-exact-audited-cap",
                        authority=cast(Any, authority),
                    )
                assert (await acquisition.allowance(actor=learner.actor))[
                    "committed_seconds"
                ] == 9_600
        finally:
            await async_engine.dispose()

    _run_async(scenario())


def test_c1_denies_over_base_for_ordinary_owner_and_unverified_grant_marker(
    postgres_harness: _Harness,
) -> None:
    async def scenario() -> None:
        async_engine = create_async_engine(
            postgres_harness.schema_url,
            connect_args={"connect_timeout": 5},
            pool_pre_ping=True,
        )
        try:
            operations = seed_operations(postgres_harness.engine)
            authority = _AllowanceAuthority(operations.tenant_id)
            ordinary = await seed(async_engine)
            ordinary_scope = await seed_budget(async_engine)
            ordinary_run = await seed_run_intent(
                async_engine,
                ordinary,
                ordinary_scope,
                allowance_seconds=3_600,
            )
            forged = await seed(async_engine)
            forged_scope = await seed_budget(async_engine)
            forged_run = await seed_run_intent(
                async_engine,
                forged,
                forged_scope,
                allowance_seconds=3_600,
            )
            async with AsyncSession(async_engine) as database, database.begin():
                row = await database.scalar(
                    select(ConversationMinuteAccount).where(
                        ConversationMinuteAccount.tenant_id == forged.tenant_id,
                        ConversationMinuteAccount.person_id == forged.person_id,
                    )
                )
                assert row is not None
                account = MinuteAccount.from_dict(row.snapshot)
                account = grant_minutes(
                    account,
                    MinuteGrant(
                        tenant_id=str(forged.tenant_id),
                        account_id=str(forged.person_id),
                        grant_id=uuid4().hex,
                        seconds=6_000,
                        authorization_ref=f"audit-event:{uuid4()}",
                        granted_by=str(operations.person_id),
                        reason="synthetic missing canonical audit event",
                    ),
                )
                row.snapshot = account.as_dict()
                row.revision += 1

            for learner, _scope_id, run_intent in (
                (ordinary, ordinary_scope, ordinary_run),
                (forged, forged_scope, forged_run),
            ):
                async with AsyncSession(async_engine) as database, database.begin():
                    acquisition = AcquisitionSessions(
                        database,
                        tenant_id=learner.tenant_id,
                        policy_revision="c1-negative-provenance-test-v1",
                        operations_tenant_id=operations.tenant_id,
                    )
                    await acquisition.reserve(source(3_500), actor=learner.actor)
                    with pytest.raises(ConversationDenied, match="remaining trial minutes"):
                        await ConversationApplication(
                            database, clock=lambda now=learner.now: now
                        ).request_run(
                            learner.actor,
                            run_intent,
                            key=f"c1-over-base-{learner.person_id.hex}",
                            authority=cast(Any, authority),
                        )
                    if learner.person_id == forged.person_id:
                        assert (await acquisition.allowance(actor=learner.actor))[
                            "allowance_seconds"
                        ] == 3_600
        finally:
            await async_engine.dispose()

    _run_async(scenario())


def test_admin_projection_separates_stored_and_effective_tester_unlimited(
    postgres_harness: _Harness,
) -> None:
    operations = seed_operations(postgres_harness.engine)

    async def scenario() -> None:
        async_engine = create_async_engine(
            postgres_harness.schema_url,
            connect_args={"connect_timeout": 5},
            pool_pre_ping=True,
        )
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        try:
            learner = await seed(async_engine)
            manager = ActorContext(
                person_id=operations.person_id,
                session_id=operations.session_id,
                tenant_id=operations.tenant_id,
                permissions=frozenset({"admin_surface"}),
            )
            async with sessions() as database, database.begin():
                await database.execute(
                    update(IdentitySession)
                    .where(IdentitySession.id == operations.session_id)
                    .values(expires_at=datetime.now(UTC) + timedelta(days=1))
                )
                await CapabilityApplication(
                    database,
                    operations_tenant_id=operations.tenant_id,
                ).bootstrap_first_manager(
                    person_id=operations.person_id,
                    command_id=uuid4(),
                    reason="Disposable tester-projection fixture",
                )
                row = await database.scalar(
                    select(ConversationMinuteAccount).where(
                        ConversationMinuteAccount.tenant_id == learner.tenant_id,
                        ConversationMinuteAccount.person_id == learner.person_id,
                    )
                )
                if row is None:
                    stale = MinuteAccount(
                        tenant_id=str(learner.tenant_id),
                        account_id=str(learner.person_id),
                    )
                    row = ConversationMinuteAccount(
                        tenant_id=learner.tenant_id,
                        person_id=learner.person_id,
                        snapshot=stale.as_dict(),
                        revision=1,
                    )
                    database.add(row)
                else:
                    stale = MinuteAccount.from_dict(row.snapshot)
                row.snapshot = MinuteAccount(
                    tenant_id=stale.tenant_id,
                    account_id=stale.account_id,
                    unlimited=True,
                    grants=stale.grants,
                    reservations=stale.reservations,
                ).as_dict()
                row.revision += 1

            target = (
                f"/v1/admin/conversation-minute-accounts/{learner.tenant_id}/{learner.person_id}"
            )
            for app, expected_effective in (
                (
                    _manager_app(
                        sessions=sessions,
                        actor=manager,
                        operations_tenant_id=operations.tenant_id,
                    ),
                    False,
                ),
                (
                    _manager_app(
                        sessions=sessions,
                        actor=manager,
                        operations_tenant_id=operations.tenant_id,
                        tester_policy=_CurrentAccountMinutePolicy(),
                    ),
                    True,
                ),
            ):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="https://admin.authorityclosers.test",
                ) as client:
                    response = await client.get(target)
                assert response.status_code == 200, response.text
                payload = response.json()
                assert payload["stored_unlimited"] is True
                assert payload["effective_unlimited"] is expected_effective
        finally:
            await async_engine.dispose()

    _run_async(scenario())


def test_cumulative_admin_grant_rejects_unrepresentable_seconds_without_partial_write(
    postgres_harness: _Harness,
) -> None:
    operations = seed_operations(postgres_harness.engine)

    async def scenario() -> None:
        async_engine = create_async_engine(
            postgres_harness.schema_url,
            connect_args={"connect_timeout": 5},
            pool_pre_ping=True,
        )
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        try:
            learner = await seed(async_engine)
            manager = ActorContext(
                person_id=operations.person_id,
                session_id=operations.session_id,
                tenant_id=operations.tenant_id,
                permissions=frozenset({"admin_surface"}),
            )
            existing_seconds = ((MAX_SAFE_JSON_INTEGER - 3_600) // 60) * 60
            async with sessions() as database, database.begin():
                await database.execute(
                    update(IdentitySession)
                    .where(IdentitySession.id == operations.session_id)
                    .values(expires_at=datetime.now(UTC) + timedelta(days=1))
                )
                await CapabilityApplication(
                    database,
                    operations_tenant_id=operations.tenant_id,
                ).bootstrap_first_manager(
                    person_id=operations.person_id,
                    command_id=uuid4(),
                    reason="Disposable integer-range fixture",
                )
                row = await database.scalar(
                    select(ConversationMinuteAccount).where(
                        ConversationMinuteAccount.tenant_id == learner.tenant_id,
                        ConversationMinuteAccount.person_id == learner.person_id,
                    )
                )
                if row is None:
                    account = MinuteAccount(
                        tenant_id=str(learner.tenant_id),
                        account_id=str(learner.person_id),
                    )
                    row = ConversationMinuteAccount(
                        tenant_id=learner.tenant_id,
                        person_id=learner.person_id,
                        snapshot=account.as_dict(),
                        revision=1,
                    )
                    database.add(row)
                else:
                    account = MinuteAccount.from_dict(row.snapshot)
                row.snapshot = MinuteAccount(
                    tenant_id=account.tenant_id,
                    account_id=account.account_id,
                    grants=(
                        MinuteGrant(
                            tenant_id=str(learner.tenant_id),
                            account_id=str(learner.person_id),
                            grant_id=uuid4().hex,
                            seconds=existing_seconds,
                            authorization_ref="legacy:synthetic-boundary-fixture",
                            granted_by=str(operations.person_id),
                            reason="Synthetic prior balance at JSON integer boundary",
                        ),
                    ),
                ).as_dict()
                row.revision += 1
                original_revision = row.revision

            app = _manager_app(
                sessions=sessions,
                actor=manager,
                operations_tenant_id=operations.tenant_id,
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://admin.authorityclosers.test",
            ) as client:
                response = await client.post(
                    f"/v1/admin/conversation-minute-accounts/"
                    f"{learner.tenant_id}/{learner.person_id}/grants",
                    json={"minutes": 1, "reason": "Would exceed exact JSON seconds range"},
                    headers={
                        "Origin": "https://admin.authorityclosers.test",
                        "Idempotency-Key": "cumulative-json-safe-integer-boundary",
                    },
                )
            assert response.status_code == 422

            async with sessions() as database, database.begin():
                row = await database.scalar(
                    select(ConversationMinuteAccount).where(
                        ConversationMinuteAccount.tenant_id == learner.tenant_id,
                        ConversationMinuteAccount.person_id == learner.person_id,
                    )
                )
                assert row is not None
                assert row.revision == original_revision
                persisted = MinuteAccount.from_dict(row.snapshot)
                assert [grant.seconds for grant in persisted.grants] == [existing_seconds]
                grant_audit_count = await database.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(
                        AuditEvent.tenant_id == operations.tenant_id,
                        AuditEvent.action == MINUTE_GRANT_ACTION,
                        AuditEvent.resource_type == "conversation_minute_grant",
                    )
                )
                assert grant_audit_count == 0
        finally:
            await async_engine.dispose()

    _run_async(scenario())
