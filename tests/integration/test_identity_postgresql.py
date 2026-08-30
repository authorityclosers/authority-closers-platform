"""Deterministic PostgreSQL concurrency coverage for the identity boundary."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Coroutine, Generator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, delete, select, update
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session as DbSession

from ac_platform.identity.application import (
    AsyncIdentityApplication,
    ProductionTransactionRequiredError,
)
from ac_platform.identity.models import (
    AuthenticationReplay,
    DeletionRequest,
    Person,
    ProviderAuthorizationTransaction,
    ProviderIdentity,
)
from ac_platform.identity.models import Session as SessionRow
from ac_platform.identity.repositories import (
    AsyncSqlAlchemyIdentityRepository,
    SqlAlchemyIdentityStore,
)
from ac_platform.identity.retention import purge_expired_identity_artifacts
from ac_platform.identity.services import (
    AuthenticationReplayError,
    ConflictingProviderIdentityError,
    InvalidSessionTokenError,
    IssuedProviderAuthorization,
    PersonSnapshot,
    ProviderAuthorizationType,
    ProviderIdentitySnapshot,
    SessionRevisionConflictError,
    SessionService,
    TenantScopeDeniedError,
    VerifiedProviderAssertion,
    issue_provider_authorization,
)
from ac_platform.tenancy.models import Membership, Tenant

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)
EMAIL = "postgres-review@authorityclosers.com"
PEPPER = b"identity-postgres-test-pepper-32b"


def _run_async_scenario(scenario: Coroutine[Any, Any, None]) -> None:
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            runner.run(scenario)
    else:
        asyncio.run(scenario)


def _postgres_url() -> str:
    raw = os.getenv("AC_IDENTITY_POSTGRES_TEST_URL") or os.getenv("AC_DATABASE_MIGRATOR_URL")
    if not raw:
        pytest.skip("PostgreSQL identity integration URL is not configured")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql":
        pytest.skip("identity concurrency coverage requires PostgreSQL")
    if (
        url.host not in {"127.0.0.1", "localhost", "::1"}
        and os.getenv("AC_IDENTITY_ALLOW_REMOTE_TEST_DATABASE") != "1"
    ):
        pytest.skip("refusing to mutate a non-local PostgreSQL database")
    return url.render_as_string(hide_password=False)


@pytest.fixture()
def postgres_engine() -> Generator[Engine, None, None]:
    engine = create_engine(_postgres_url(), pool_size=8, max_overflow=0)
    try:
        assert engine.dialect.name == "postgresql"
        yield engine
    finally:
        engine.dispose()


def _person(person_id: UUID, *, email: str = EMAIL) -> PersonSnapshot:
    return PersonSnapshot(
        id=person_id,
        email=email,
        email_verified_at=NOW,
    )


def _cleanup(
    engine: Engine,
    *,
    person_ids: tuple[UUID, ...],
    tenant_ids: tuple[UUID, ...] = (),
    replay_keys: tuple[str, ...] = (),
    transaction_ids: tuple[UUID, ...] = (),
) -> None:
    with engine.begin() as connection:
        if replay_keys:
            connection.execute(
                delete(AuthenticationReplay).where(AuthenticationReplay.replay_key.in_(replay_keys))
            )
        if transaction_ids:
            connection.execute(
                delete(ProviderAuthorizationTransaction).where(
                    ProviderAuthorizationTransaction.id.in_(transaction_ids)
                )
            )
        connection.execute(delete(DeletionRequest).where(DeletionRequest.person_id.in_(person_ids)))
        connection.execute(
            delete(ProviderIdentity).where(ProviderIdentity.person_id.in_(person_ids))
        )
        connection.execute(delete(SessionRow).where(SessionRow.person_id.in_(person_ids)))
        if tenant_ids:
            connection.execute(delete(Membership).where(Membership.tenant_id.in_(tenant_ids)))
            connection.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))
        connection.execute(delete(Person).where(Person.id.in_(person_ids)))


def test_postgresql_session_cas_preserves_concurrent_revocation(
    postgres_engine: Engine,
) -> None:
    person_id = uuid4()
    try:
        with DbSession(postgres_engine) as database:
            store = SqlAlchemyIdentityStore(database)
            store.save_person(_person(person_id))
            issued = SessionService(store, token_pepper=PEPPER).issue(person_id, now=NOW)
            database.commit()

        async def run_scenario() -> None:
            async_engine = create_async_engine(_postgres_url(), pool_size=4, max_overflow=0)
            sessions = async_sessionmaker(async_engine, expire_on_commit=False)
            try:
                async with sessions() as first, sessions() as second:
                    first_store = AsyncSqlAlchemyIdentityRepository(first)
                    second_store = AsyncSqlAlchemyIdentityRepository(second)
                    async with first.begin():
                        first_snapshot = await first_store.get_session(issued.metadata.id)
                    async with second.begin():
                        stale_snapshot = await second_store.get_session(issued.metadata.id)
                    assert first_snapshot is not None and stale_snapshot is not None

                    async with first.begin():
                        await first_store.save_session(
                            replace(
                                first_snapshot,
                                revoked_at=NOW + timedelta(seconds=1),
                                revision=first_snapshot.revision + 1,
                            )
                        )
                    with pytest.raises(SessionRevisionConflictError):
                        async with second.begin():
                            await second_store.save_session(
                                replace(
                                    stale_snapshot,
                                    last_seen_at=NOW + timedelta(seconds=2),
                                    revision=stale_snapshot.revision + 1,
                                )
                            )
                    async with second.begin():
                        canonical = await second_store.get_session(issued.metadata.id)
                    assert canonical is not None and canonical.revoked_at is not None
            finally:
                await async_engine.dispose()

        _run_async_scenario(run_scenario())
    finally:
        _cleanup(postgres_engine, person_ids=(person_id,))


def test_postgresql_application_requires_an_explicit_caller_transaction() -> None:
    async def run_scenario() -> None:
        async_engine = create_async_engine(_postgres_url(), pool_size=2, max_overflow=0)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        try:
            async with sessions() as database:
                await database.execute(select(1))
                application = AsyncIdentityApplication(database, token_pepper=PEPPER)
                with pytest.raises(ProductionTransactionRequiredError):
                    await application.resolve_actor("x" * 43, now=NOW)
                await database.rollback()

                async with database.begin():
                    with pytest.raises(InvalidSessionTokenError):
                        await application.resolve_actor("x" * 43, now=NOW)
        finally:
            await async_engine.dispose()

    _run_async_scenario(run_scenario())


def test_postgresql_deletion_constraint_rejects_impossible_terminal_time(
    postgres_engine: Engine,
) -> None:
    person_id = uuid4()
    try:
        with DbSession(postgres_engine) as database:
            database.add(Person(id=person_id))
            database.commit()
            database.add(
                DeletionRequest(
                    id=uuid4(),
                    person_id=person_id,
                    status="completed",
                    requested_at=NOW,
                    completed_at=NOW - timedelta(seconds=1),
                )
            )
            with pytest.raises(IntegrityError):
                database.flush()
            database.rollback()
    finally:
        _cleanup(postgres_engine, person_ids=(person_id,))


class _BarrierIdentityRepository(AsyncSqlAlchemyIdentityRepository):
    def __init__(self, database: AsyncSession, barrier: asyncio.Barrier) -> None:
        super().__init__(database)
        self._barrier = barrier
        self._first_lookup = True

    async def find_provider_identities_for_update(
        self, issuer: str, subject: str
    ) -> tuple[ProviderIdentitySnapshot, ...]:
        matches = tuple(await super().find_provider_identities_for_update(issuer, subject))
        if self._first_lookup:
            self._first_lookup = False
            await asyncio.wait_for(self._barrier.wait(), timeout=10)
        return matches


def test_postgresql_provider_link_race_has_one_canonical_owner(
    postgres_engine: Engine,
) -> None:
    first_person_id = uuid4()
    second_person_id = uuid4()
    subject = f"provider-race-{uuid4()}"
    emails = {
        first_person_id: f"provider-race-{first_person_id}@authorityclosers.test",
        second_person_id: f"provider-race-{second_person_id}@authorityclosers.test",
    }
    tokens: dict[UUID, str] = {}
    transactions: dict[UUID, IssuedProviderAuthorization] = {}
    with DbSession(postgres_engine) as database:
        store = SqlAlchemyIdentityStore(database)
        for person_id in (first_person_id, second_person_id):
            store.save_person(_person(person_id, email=emails[person_id]))
            tokens[person_id] = (
                SessionService(store, token_pepper=PEPPER)
                .issue(
                    person_id,
                    now=NOW,
                )
                .token
            )
            transactions[person_id] = issue_provider_authorization(
                store,
                authorization_type=ProviderAuthorizationType.LINK,
                audience="authority-closers-web",
                issued_at=NOW,
                expires_in=timedelta(minutes=10),
                person_id=person_id,
            )
        database.commit()

    async def run_scenario() -> None:
        async_engine = create_async_engine(_postgres_url(), pool_size=4, max_overflow=0)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        barrier = asyncio.Barrier(2)
        outcomes: list[tuple[str, UUID]] = []

        async def link(person_id: UUID) -> None:
            transaction = transactions[person_id]
            try:
                async with sessions() as database, database.begin():
                    application = AsyncIdentityApplication(database, token_pepper=PEPPER)
                    application._repository = _BarrierIdentityRepository(  # noqa: SLF001
                        database,
                        barrier,
                    )
                    linked = await application.link_provider_for_session(
                        tokens[person_id],
                        transaction.transaction_id,
                        assertion=VerifiedProviderAssertion(
                            issuer="https://issuer.postgres.test",
                            subject=subject,
                            audience="authority-closers-web",
                            state=transaction.state,
                            nonce=transaction.nonce,
                            authorization_type=ProviderAuthorizationType.LINK,
                            email=emails[person_id],
                            email_verified=True,
                        ),
                        pkce_verifier=transaction.pkce_verifier,
                        now=NOW,
                    )
                outcome = ("linked", linked.person_id)
            except ConflictingProviderIdentityError:
                outcome = ("conflict", person_id)
            outcomes.append(outcome)

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    link(first_person_id),
                    link(second_person_id),
                ),
                timeout=20,
            )
        finally:
            await async_engine.dispose()

        assert sorted(outcome for outcome, _ in outcomes) == ["conflict", "linked"]

    try:
        _run_async_scenario(run_scenario())
        with postgres_engine.connect() as connection:
            owners = connection.scalars(
                select(ProviderIdentity.person_id).where(
                    ProviderIdentity.issuer == "https://issuer.postgres.test",
                    ProviderIdentity.subject == subject,
                )
            ).all()
        assert len(owners) == 1
    finally:
        _cleanup(
            postgres_engine,
            person_ids=(first_person_id, second_person_id),
            transaction_ids=tuple(
                transaction.transaction_id for transaction in transactions.values()
            ),
        )


def test_postgresql_identity_retention_is_bounded_and_preserves_fresh_rows(
    postgres_engine: Engine,
) -> None:
    expired_transaction_ids = (uuid4(), uuid4())
    fresh_transaction_id = uuid4()
    expired_replay_keys = (f"retention-expired-{uuid4()}", f"retention-expired-{uuid4()}")
    fresh_replay_key = f"retention-fresh-{uuid4()}"
    all_transaction_ids = (*expired_transaction_ids, fresh_transaction_id)
    all_replay_keys = (*expired_replay_keys, fresh_replay_key)
    try:
        with postgres_engine.begin() as connection:
            for position, transaction_id in enumerate(all_transaction_ids):
                expired = transaction_id != fresh_transaction_id
                issued_at = NOW - timedelta(days=3, minutes=position)
                connection.execute(
                    ProviderAuthorizationTransaction.__table__.insert().values(
                        id=transaction_id,
                        authorization_type="authenticate",
                        audience="authority-closers-web",
                        state_hash=bytes([position + 1]) * 32,
                        nonce_hash=bytes([position + 11]) * 32,
                        pkce_verifier_hash=bytes([position + 21]) * 32,
                        person_id=None,
                        issued_at=issued_at,
                        expires_at=(
                            issued_at + timedelta(minutes=10)
                            if expired
                            else NOW + timedelta(hours=1)
                        ),
                        status="issued",
                        consumed_at=None,
                    )
                )
            for position, replay_key in enumerate(all_replay_keys):
                expired = replay_key != fresh_replay_key
                consumed_at = NOW - timedelta(days=3, minutes=position)
                connection.execute(
                    AuthenticationReplay.__table__.insert().values(
                        replay_key=replay_key,
                        consumed_at=consumed_at,
                        expires_at=(
                            consumed_at + timedelta(hours=1)
                            if expired
                            else NOW + timedelta(hours=1)
                        ),
                    )
                )

        async def run_scenario() -> None:
            async_engine = create_async_engine(_postgres_url(), pool_size=2, max_overflow=0)
            sessions = async_sessionmaker(async_engine, expire_on_commit=False)
            try:
                async with sessions() as database, database.begin():
                    first = await purge_expired_identity_artifacts(
                        database,
                        now=NOW + timedelta(days=1),
                        retain_for=timedelta(days=1),
                        batch_size=1,
                    )
                assert first.provider_authorization_transactions == 1
                assert first.authentication_replays == 1

                async with sessions() as database, database.begin():
                    second = await purge_expired_identity_artifacts(
                        database,
                        now=NOW + timedelta(days=1),
                        retain_for=timedelta(days=1),
                        batch_size=10,
                    )
                assert second.provider_authorization_transactions == 1
                assert second.authentication_replays == 1

                async with sessions() as database:
                    remaining_transactions = set(
                        (
                            await database.scalars(
                                select(ProviderAuthorizationTransaction.id).where(
                                    ProviderAuthorizationTransaction.id.in_(all_transaction_ids)
                                )
                            )
                        ).all()
                    )
                    remaining_replays = set(
                        (
                            await database.scalars(
                                select(AuthenticationReplay.replay_key).where(
                                    AuthenticationReplay.replay_key.in_(all_replay_keys)
                                )
                            )
                        ).all()
                    )
                assert remaining_transactions == {fresh_transaction_id}
                assert remaining_replays == {fresh_replay_key}
            finally:
                await async_engine.dispose()

        _run_async_scenario(run_scenario())
    finally:
        _cleanup(
            postgres_engine,
            person_ids=(),
            replay_keys=all_replay_keys,
            transaction_ids=all_transaction_ids,
        )


def test_postgresql_async_provider_authorization_is_issued_then_consumed_once(
    postgres_engine: Engine,
) -> None:
    person_id = uuid4()
    provider = ProviderIdentity(
        id=uuid4(),
        person_id=person_id,
        issuer="https://issuer.postgres.test",
        subject=f"auth-{uuid4()}",
    )
    provider_issuer = provider.issuer
    provider_subject = provider.subject
    issued: IssuedProviderAuthorization | None = None
    with DbSession(postgres_engine) as database:
        store = SqlAlchemyIdentityStore(database)
        store.save_person(_person(person_id))
        database.add(provider)
        database.commit()

    async def run_scenario() -> None:
        nonlocal issued
        async_engine = create_async_engine(_postgres_url(), pool_size=4, max_overflow=0)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        try:
            async with sessions() as database, database.begin():
                application = AsyncIdentityApplication(database, token_pepper=PEPPER)
                issued = await application.begin_provider_authorization(
                    ProviderAuthorizationType.AUTHENTICATE,
                    "authority-closers-web",
                    now=NOW,
                )

            assert issued is not None
            assertion = VerifiedProviderAssertion(
                issuer=provider_issuer,
                subject=provider_subject,
                audience=issued.audience,
                state=issued.state,
                nonce=issued.nonce,
                authorization_type=ProviderAuthorizationType.AUTHENTICATE,
                email=EMAIL,
                email_verified=True,
            )
            async with sessions() as database, database.begin():
                application = AsyncIdentityApplication(database, token_pepper=PEPPER)
                session = await application.authenticate_provider(
                    issued.transaction_id,
                    assertion,
                    pkce_verifier=issued.pkce_verifier,
                    now=NOW,
                )
                assert session.metadata.person_id == person_id

            async with sessions() as database, database.begin():
                application = AsyncIdentityApplication(database, token_pepper=PEPPER)
                with pytest.raises(AuthenticationReplayError):
                    await application.authenticate_provider(
                        issued.transaction_id,
                        assertion,
                        pkce_verifier=issued.pkce_verifier,
                        now=NOW,
                    )
                row = await database.scalar(
                    select(ProviderAuthorizationTransaction).where(
                        ProviderAuthorizationTransaction.id == issued.transaction_id
                    )
                )
                assert row is not None
                assert row.status == "consumed"
        finally:
            await async_engine.dispose()

    try:
        _run_async_scenario(run_scenario())
    finally:
        _cleanup(
            postgres_engine,
            person_ids=(person_id,),
            transaction_ids=() if issued is None else (issued.transaction_id,),
        )


def test_postgresql_tenant_selection_serializes_membership_revocation(
    postgres_engine: Engine,
) -> None:
    person_id = uuid4()
    tenant_id = uuid4()
    slug = f"identity-lock-{uuid4().hex[:12]}"
    token: str
    with DbSession(postgres_engine) as database:
        store = SqlAlchemyIdentityStore(database)
        store.save_person(_person(person_id))
        database.add(Tenant(id=tenant_id, slug=slug, name="Identity lock test"))
        database.flush()
        database.add(
            Membership(
                tenant_id=tenant_id,
                person_id=person_id,
                role="learner",
            )
        )
        token = (
            SessionService(store, token_pepper=PEPPER)
            .issue(
                person_id,
                now=NOW,
            )
            .token
        )
        database.commit()

    try:

        async def run_scenario() -> None:
            async_engine = create_async_engine(_postgres_url(), pool_size=4, max_overflow=0)
            sessions = async_sessionmaker(async_engine, expire_on_commit=False)
            selected = asyncio.Event()
            release_selection = asyncio.Event()
            revocation_started = asyncio.Event()

            async def select_context() -> None:
                async with sessions() as database, database.begin():
                    application = AsyncIdentityApplication(database, token_pepper=PEPPER)
                    resolved = await application.select_tenant(token, tenant_id, now=NOW)
                    assert resolved.actor.tenant_id == tenant_id
                    selected.set()
                    await release_selection.wait()

            async def revoke_membership() -> None:
                async with sessions() as database, database.begin():
                    revocation_started.set()
                    await database.execute(
                        update(Membership)
                        .where(
                            Membership.tenant_id == tenant_id,
                            Membership.person_id == person_id,
                        )
                        .values(
                            status="inactive",
                            ended_at=NOW + timedelta(seconds=1),
                            revision=Membership.revision + 1,
                        )
                    )

            selection_task = asyncio.create_task(select_context())
            revocation_task: asyncio.Task[None] | None = None
            try:
                await asyncio.wait_for(selected.wait(), timeout=10)
                revocation_task = asyncio.create_task(revoke_membership())
                await asyncio.wait_for(revocation_started.wait(), timeout=10)
                await asyncio.sleep(0.25)
                assert not revocation_task.done(), "membership update bypassed the selection lock"
                release_selection.set()
                await asyncio.wait_for(selection_task, timeout=10)
                await asyncio.wait_for(revocation_task, timeout=10)

                async with sessions() as database, database.begin():
                    application = AsyncIdentityApplication(database, token_pepper=PEPPER)
                    with pytest.raises(TenantScopeDeniedError):
                        await application.resolve_actor(token, require_tenant=True, now=NOW)
            finally:
                release_selection.set()
                tasks = [selection_task]
                if revocation_task is not None:
                    tasks.append(revocation_task)
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await async_engine.dispose()

        _run_async_scenario(run_scenario())
    finally:
        _cleanup(postgres_engine, person_ids=(person_id,), tenant_ids=(tenant_id,))
