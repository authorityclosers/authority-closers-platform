"""Disposable PostgreSQL proof for the held verification-email bootstrap path."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Coroutine, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, make_url
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from ac_platform.bootstrap.verification_email import (
    INITIAL_BOOTSTRAP_GENERATION,
    INITIAL_BOOTSTRAP_HOLD_REASON,
    VerificationEmailBootstrapApplication,
    VerificationEmailBootstrapCommand,
    VerificationEmailBootstrapError,
)
from ac_platform.identity.models import EmailChallenge, EmailChallengeKind
from ac_platform.identity.password_auth import (
    PASSWORD_EMAIL_VERIFICATION_EVENT,
    PasswordIdentityService,
    decrypt_challenge_token,
)
from ac_platform.kernel.events import EventCategory, EventEnvelope
from ac_platform.outbox.models import (
    Job,
    JobStatus,
    OperationsRecoveryState,
    RecoveryStatus,
)
from ac_platform.outbox.repository import LeaseLostError, OutboxRepository
from ac_platform.providers import FakeEmailAdapter
from ac_platform.tenancy.models import Tenant

ROOT = Path(__file__).parents[2]
TOKEN_SECRET = b"postgres-verification-email-test-secret-32-bytes"
NOW = datetime(2026, 9, 13, 12, tzinfo=UTC)


def _run_async[T](coroutine: Coroutine[Any, Any, T]) -> T:
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


def _postgres_url() -> URL:
    raw = os.getenv("AC_VERIFICATION_EMAIL_POSTGRES_TEST_URL") or os.getenv("AC_TEST_DATABASE_URL")
    if not raw:
        pytest.skip(
            "AC_VERIFICATION_EMAIL_POSTGRES_TEST_URL or AC_TEST_DATABASE_URL is not configured"
        )
    url = make_url(raw)
    if url.get_backend_name() != "postgresql":
        pytest.fail("verification-email integration requires PostgreSQL")
    if (
        url.host not in {None, "127.0.0.1", "localhost", "::1"}
        and os.getenv("AC_ALLOW_REMOTE_TEST_DATABASE") != "1"
    ):
        pytest.skip("refusing to mutate a non-local PostgreSQL database")
    return url.set(drivername="postgresql+psycopg")


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[URL]:
    base_url = _postgres_url()
    schema = f"verification_email_{uuid4().hex}"
    admin_engine = create_engine(base_url, pool_pre_ping=True)
    created = False
    try:
        with Session(admin_engine) as session:
            session.execute(CreateSchema(schema))
            session.commit()
        created = True
        query = dict(base_url.query)
        query["options"] = f"-csearch_path={schema}"
        schema_url = base_url.set(query=query)
        environment = os.environ.copy()
        environment.update(
            {
                "AC_DATABASE_URL": base_url.render_as_string(hide_password=False),
                "AC_DATABASE_MIGRATOR_URL": base_url.render_as_string(hide_password=False),
                "AC_ENVIRONMENT": "test",
                "PGOPTIONS": f"-csearch_path={schema}",
                "PYTHONPATH": os.pathsep.join(
                    part
                    for part in (
                        str(ROOT / "packages" / "python"),
                        environment.get("PYTHONPATH", ""),
                    )
                    if part
                ),
            }
        )
        migration = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if migration.returncode != 0:
            pytest.fail(f"isolated PostgreSQL migration failed: {migration.stderr[-2000:]}")
        yield schema_url
    finally:
        if created:
            with Session(admin_engine) as session:
                session.execute(DropSchema(schema, cascade=True))
                session.commit()
        admin_engine.dispose()


@dataclass(frozen=True, slots=True)
class _Case:
    operations_tenant_id: UUID
    person_id: UUID
    challenge_id: UUID
    command: VerificationEmailBootstrapCommand
    token: str


def _settings() -> Any:
    return SimpleNamespace(
        email_challenge_secret=SecretStr(TOKEN_SECRET.decode("ascii")),
        public_app_url="https://learner.example.test",
    )


async def _reset_recovery(sessions: async_sessionmaker[Any]) -> None:
    async with sessions() as database, database.begin():
        state = await database.get(OperationsRecoveryState, 1, with_for_update=True)
        assert state is not None
        state.generation = INITIAL_BOOTSTRAP_GENERATION
        state.status = RecoveryStatus.HELD.value
        state.hold_reason = INITIAL_BOOTSTRAP_HOLD_REASON
        state.reconciled_at = None
        state.reconciled_by = None
        state.reconciliation_reason = None


async def _seed_case(engine: AsyncEngine) -> _Case:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    await _reset_recovery(sessions)
    operations_tenant_id = uuid4()
    email = f"verification-{uuid4().hex}@example.test"
    async with sessions() as database, database.begin():
        database.add(
            Tenant(
                id=operations_tenant_id,
                slug=f"operations-{uuid4().hex}",
                name="Operations Test Tenant",
                status="active",
            )
        )
        registration = await PasswordIdentityService(
            database,
            token_secret=TOKEN_SECRET,
        ).register(
            email=email,
            first_name="Dipak",
            whatsapp_number="+919999999999",
            password="a-valid-password-123",  # noqa: S106 - disposable test credential
            consent_version="test-v1",
            now=NOW,
        )
        assert registration.created is True
        assert registration.person_id is not None
        assert registration.challenge is not None
        challenge = await database.get(EmailChallenge, registration.challenge.challenge_id)
        assert challenge is not None
        token = decrypt_challenge_token(
            TOKEN_SECRET,
            challenge.encrypted_token,
            kind=EmailChallengeKind.VERIFICATION,
            person_id=registration.person_id,
        )
        event = await OutboxRepository(database).enqueue(
            EventEnvelope(
                name=PASSWORD_EMAIL_VERIFICATION_EVENT,
                category=EventCategory.OPERATIONAL,
                aggregate_type="person",
                aggregate_id=registration.person_id,
                tenant_id=None,
                payload={
                    "challenge_id": str(registration.challenge.challenge_id),
                    "kind": EmailChallengeKind.VERIFICATION.value,
                },
            ),
            dedupe_key=f"identity-email:email_verification:{registration.challenge.challenge_id}",
        )
    return _Case(
        operations_tenant_id=operations_tenant_id,
        person_id=registration.person_id,
        challenge_id=registration.challenge.challenge_id,
        command=VerificationEmailBootstrapCommand(
            command_id=uuid4(),
            person_id=registration.person_id,
            challenge_id=registration.challenge.challenge_id,
            expected_email=email,
            operator_reference=f"postgres-proof-{event.id}",
            reason="disposable held bootstrap proof",
        ),
        token=token,
    )


async def _prepare(
    engine: AsyncEngine,
    case: _Case,
) -> Any:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as database, database.begin():
        return await VerificationEmailBootstrapApplication(
            database,
            operations_tenant_id=case.operations_tenant_id,
        ).prepare(case.command)


async def _send(
    engine: AsyncEngine,
    case: _Case,
    provider: Any,
) -> tuple[Any, Any]:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    prepared = await _prepare(engine, case)
    async with sessions() as database, database.begin():
        lease = await VerificationEmailBootstrapApplication(
            database,
            operations_tenant_id=case.operations_tenant_id,
        ).claim(prepared)
    assert lease is not None
    async with sessions() as database, database.begin():
        message = await VerificationEmailBootstrapApplication(
            database,
            operations_tenant_id=case.operations_tenant_id,
        ).begin_dispatch(prepared, lease, settings=_settings())
    async with sessions() as database, database.begin():
        receipt = await VerificationEmailBootstrapApplication(
            database,
            operations_tenant_id=case.operations_tenant_id,
        ).dispatch(prepared, lease, message=message, provider=provider)
    return prepared, receipt


async def _job(engine: AsyncEngine, job_id: UUID) -> Job:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as database:
        row = await database.get(Job, job_id)
        assert row is not None
        return row


def test_held_bootstrap_receipt_replay_and_normal_token_consumption(
    postgres_harness: URL,
) -> None:
    engine = create_async_engine(postgres_harness, pool_size=4, max_overflow=0)
    try:

        async def scenario() -> None:
            case = await _seed_case(engine)
            provider = FakeEmailAdapter()
            prepared, receipt = await _send(engine, case, provider)
            assert receipt.accepted is True
            assert receipt.idempotency_key == f"outbox:{prepared.event_id}"
            assert len(provider.deliveries) == 1

            token = provider.sent_messages[0].variables["action_link"].split("#token=", 1)[1]
            assert token == case.token
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as database, database.begin():
                person = await PasswordIdentityService(
                    database,
                    token_secret=TOKEN_SECRET,
                ).consume_verification(token, now=NOW + timedelta(minutes=1))
                assert person.email_verified_at is not None

            replay = await _prepare(engine, case)
            async with sessions() as database, database.begin():
                lease = await VerificationEmailBootstrapApplication(
                    database,
                    operations_tenant_id=case.operations_tenant_id,
                ).claim(replay)
                assert lease is None
                result = await VerificationEmailBootstrapApplication(
                    database,
                    operations_tenant_id=case.operations_tenant_id,
                ).result_for_succeeded(replay)
            assert result.replayed is True
            assert result.provider_message_id == receipt.provider_message_id
            assert len(provider.deliveries) == 1
            row = await _job(engine, prepared.job_id)
            assert row.status == JobStatus.SUCCEEDED.value
            assert row.provider_receipt is not None

        _run_async(scenario())
    finally:
        _run_async(engine.dispose())


def test_bootstrap_refuses_expired_consumed_and_restored_inputs(postgres_harness: URL) -> None:
    engine = create_async_engine(postgres_harness, pool_size=3, max_overflow=0)
    try:

        async def scenario() -> None:
            expired = await _seed_case(engine)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as database, database.begin():
                challenge = await database.get(EmailChallenge, expired.challenge_id)
                assert challenge is not None
                expired_at = datetime.now(UTC) - timedelta(hours=1)
                challenge.issued_at = expired_at - timedelta(hours=1)
                challenge.expires_at = expired_at
            with pytest.raises(VerificationEmailBootstrapError, match="expired"):
                await _prepare(engine, expired)

            consumed = await _seed_case(engine)
            async with sessions() as database, database.begin():
                challenge = await database.get(EmailChallenge, consumed.challenge_id)
                assert challenge is not None
                challenge.consumed_at = NOW
            with pytest.raises(VerificationEmailBootstrapError, match="consumed"):
                await _prepare(engine, consumed)

            restored = await _seed_case(engine)
            async with sessions() as database, database.begin():
                state = await database.get(OperationsRecoveryState, 1, with_for_update=True)
                assert state is not None
                state.generation = 2
                state.hold_reason = "database_restore_requires_reconciliation"
            with pytest.raises(VerificationEmailBootstrapError, match="initial recovery hold"):
                await _prepare(engine, restored)

        _run_async(scenario())
    finally:
        _run_async(engine.dispose())


def test_ambiguous_provider_receipt_is_durable_and_blocks_reclaim(postgres_harness: URL) -> None:
    engine = create_async_engine(postgres_harness, pool_size=4, max_overflow=0)
    try:

        async def scenario() -> None:
            case = await _seed_case(engine)
            prepared = await _prepare(engine, case)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as database, database.begin():
                lease = await VerificationEmailBootstrapApplication(
                    database,
                    operations_tenant_id=case.operations_tenant_id,
                ).claim(prepared)
            assert lease is not None
            async with sessions() as database, database.begin():
                message = await VerificationEmailBootstrapApplication(
                    database,
                    operations_tenant_id=case.operations_tenant_id,
                ).begin_dispatch(prepared, lease, settings=_settings())

            class UncertainProvider:
                async def send(self, _message: Any) -> Any:
                    raise RuntimeError("provider response was lost")

            with pytest.raises(RuntimeError, match="response was lost"):
                async with sessions() as database, database.begin():
                    await VerificationEmailBootstrapApplication(
                        database,
                        operations_tenant_id=case.operations_tenant_id,
                    ).dispatch(prepared, lease, message=message, provider=UncertainProvider())
            async with sessions() as database, database.begin():
                await VerificationEmailBootstrapApplication(
                    database,
                    operations_tenant_id=case.operations_tenant_id,
                ).record_failure(
                    prepared,
                    lease,
                    RuntimeError("provider response was lost"),
                    ambiguous=True,
                )
            row = await _job(engine, prepared.job_id)
            assert row.status == JobStatus.DEAD_LETTER.value
            assert row.delivery_ambiguous_at is not None
            assert row.dispatch_started_at is not None
            with pytest.raises(LeaseLostError, match="unavailable"):
                async with sessions() as database, database.begin():
                    replay = await _prepare(engine, case)
                    await VerificationEmailBootstrapApplication(
                        database,
                        operations_tenant_id=case.operations_tenant_id,
                    ).claim(replay)

        _run_async(scenario())
    finally:
        _run_async(engine.dispose())
