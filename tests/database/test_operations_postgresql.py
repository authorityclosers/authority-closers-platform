"""Disposable PostgreSQL checks for operations fences and audit triggers.

Set ``AC_OPERATIONS_POSTGRES_TEST_URL`` to a disposable database with the
Alembic head applied before running this module.  The normal SQLite suite
remains the fast local gate; these checks exercise PostgreSQL row locks,
database-clock predicates, and trigger behavior.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, insert, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditChainHead
from ac_platform.audit.service import AuditRepository
from ac_platform.db.models import model_metadata
from ac_platform.outbox.models import (
    Job,
    JobStatus,
    OperationsRecoveryState,
    RecoveryStatus,
)
from ac_platform.outbox.repository import (
    build_job_acknowledge_statement,
    build_job_ambiguity_statement,
    build_job_receipt_statement,
    canonical_receipt_digest,
)

if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

OPERATIONS_TABLES = {
    "outbox_events",
    "jobs",
    "operations_recovery_state",
    "provider_inbox",
    "audit_events",
    "audit_chain_heads",
}


@pytest.fixture()
def database() -> Engine:
    raw_url = os.getenv("AC_OPERATIONS_POSTGRES_TEST_URL")
    if not raw_url:
        pytest.skip("AC_OPERATIONS_POSTGRES_TEST_URL is not configured")
    engine = create_engine(raw_url)
    if engine.dialect.name != "postgresql":
        pytest.skip("AC_OPERATIONS_POSTGRES_TEST_URL must use PostgreSQL")
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        yield engine
    finally:
        engine.dispose()


def test_stale_worker_cannot_mark_a_successful_job_ambiguous(database: Engine) -> None:
    now = datetime.now(UTC)
    token = uuid4()
    job_id = uuid4()
    provider_key = f"operations-pg:{uuid4()}"
    operator_id = uuid4()

    with Session(database) as session:
        state = session.get(OperationsRecoveryState, 1)
        assert state is not None
        session.execute(
            text("INSERT INTO persons (id, email, status) VALUES (:id, :email, 'active')"),
            {"id": operator_id, "email": f"operations-{uuid4()}@example.test"},
        )
        state.status = RecoveryStatus.READY.value
        state.reconciled_at = now
        state.reconciled_by = operator_id
        state.reconciliation_reason = "disposable operations test"
        generation = state.generation
        session.execute(
            insert(Job.__table__).values(
                id=job_id,
                kind="email.enrollment_welcome.v1",
                dedupe_key=f"job:{uuid4()}",
                payload={},
                external_side_effect=True,
                recovery_generation=generation,
                status=JobStatus.LEASED.value,
                attempt_count=1,
                lease_token=token,
                leased_until=now + timedelta(minutes=5),
                provider_idempotency_key=provider_key,
                dispatch_started_at=now,
            )
        )
        session.commit()

    receipt = {"idempotency_key": provider_key, "accepted": True}
    with Session(database) as winner:
        assert (
            winner.execute(
                build_job_receipt_statement(
                    job_id=job_id,
                    lease_token=token,
                    receipt=receipt,
                    receipt_digest=canonical_receipt_digest(receipt),
                )
            ).rowcount
            == 1
        )
        assert (
            winner.execute(
                build_job_acknowledge_statement(job_id=job_id, lease_token=token)
            ).rowcount
            == 1
        )
        winner.commit()

    with Session(database) as stale:
        result = stale.execute(
            build_job_ambiguity_statement(
                job_id=job_id,
                lease_token=token,
                recovery_generation=generation,
                provider_idempotency_key=provider_key,
                error="stale worker",
            )
        )
        assert result.rowcount == 0
        row = stale.get(Job, job_id)
        assert row is not None
        assert row.status == JobStatus.SUCCEEDED.value
        assert row.delivery_ambiguous_at is None
        assert row.last_error is None


def test_operations_scope_has_no_alembic_model_drift(database: Engine) -> None:
    with database.connect() as connection:
        diffs = compare_metadata(MigrationContext.configure(connection), model_metadata())

    scoped_diffs = []
    for diff in diffs:
        table_names = {
            table.name for value in diff if (table := getattr(value, "table", None)) is not None
        }
        if table_names & OPERATIONS_TABLES:
            scoped_diffs.append(diff)
    assert scoped_diffs == []


async def test_postgresql_audit_chain_head_rejects_direct_runtime_mutation(
    database: Engine,
) -> None:
    """A non-superuser cannot mutate heads, but can use the narrow append API."""

    tenant_id = uuid4()
    runtime_role = f"ac_test_runtime_{uuid4().hex}"
    runtime_password = f"runtime-test-{uuid4().hex}"
    runtime_engine: Engine | None = None

    try:
        with database.begin() as connection:
            connection.execute(
                text(
                    f"CREATE ROLE \"{runtime_role}\" LOGIN PASSWORD '{runtime_password}' "
                    "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT"
                )
            )
            database_name = connection.scalar(text("SELECT current_database()"))
            assert isinstance(database_name, str)
            quoted_database = connection.dialect.identifier_preparer.quote_identifier(database_name)
            connection.execute(
                text(f'GRANT CONNECT ON DATABASE {quoted_database} TO "{runtime_role}"')
            )
            connection.execute(
                text(
                    "INSERT INTO tenants (id, slug, name, status) "
                    "VALUES (:id, :slug, :name, 'active')"
                ),
                {
                    "id": tenant_id,
                    "slug": f"operations-pg-{uuid4()}",
                    "name": "Operations PostgreSQL",
                },
            )
            connection.execute(text(f'GRANT USAGE ON SCHEMA public TO "{runtime_role}"'))
            connection.execute(
                text(f'GRANT SELECT, INSERT ON TABLE public.audit_events TO "{runtime_role}"')
            )
            connection.execute(
                text(f'GRANT SELECT ON TABLE public.audit_chain_heads TO "{runtime_role}"')
            )
            connection.execute(
                text(
                    f"GRANT EXECUTE ON FUNCTION public.append_audit_chain_head("
                    "uuid, integer, uuid, text, timestamptz) "
                    f'TO "{runtime_role}"'
                )
            )

        runtime_engine = create_engine(
            database.url.set(username=runtime_role, password=runtime_password)
        )

        def assert_runtime_denied(statement: str) -> None:
            assert runtime_engine is not None
            with pytest.raises(DBAPIError), runtime_engine.begin() as connection:
                connection.execute(text("SELECT set_config('ac.audit_append', '1', true)"))
                connection.execute(text(statement), {"tenant_id": tenant_id})

        assert_runtime_denied(
            "INSERT INTO public.audit_chain_heads "
            "(tenant_id, sequence_no, event_id, event_hash) "
            "VALUES (:tenant_id, 1, :tenant_id, repeat('a', 64))"
        )

        async_engine = create_async_engine(
            database.url.set(username=runtime_role, password=runtime_password)
        )
        try:
            async with AsyncSession(async_engine) as session, session.begin():
                repository = AuditRepository(session)
                first = await repository.append(
                    tenant_id=tenant_id,
                    actor_person_id=None,
                    actor_type="system",
                    action="operations.test",
                    resource_type="test",
                    payload={},
                )
                second = await repository.append(
                    tenant_id=tenant_id,
                    actor_person_id=None,
                    actor_type="system",
                    action="operations.test.next",
                    resource_type="test",
                    payload={},
                )
                assert first.sequence_no == 1
                assert second.sequence_no == 2
                assert second.previous_hash == first.event_hash
        finally:
            await async_engine.dispose()

        assert_runtime_denied(
            "UPDATE public.audit_chain_heads SET sequence_no = 2 WHERE tenant_id = :tenant_id"
        )
        assert_runtime_denied("DELETE FROM public.audit_chain_heads WHERE tenant_id = :tenant_id")
        assert_runtime_denied("TRUNCATE public.audit_chain_heads")

        with database.connect() as connection:
            function_security = connection.execute(
                text(
                    "SELECT p.prosecdef, p.proconfig, r.rolname "
                    "FROM pg_proc AS p "
                    "JOIN pg_namespace AS n ON n.oid = p.pronamespace "
                    "JOIN pg_roles AS r ON r.oid = p.proowner "
                    "WHERE n.nspname = 'public' AND p.proname = 'append_audit_chain_head'"
                )
            ).one()
        assert function_security.prosecdef is True
        assert "search_path=pg_catalog, public, pg_temp" in function_security.proconfig
        assert function_security.rolname != runtime_role

        with Session(runtime_engine) as runtime_session:
            head = runtime_session.get(AuditChainHead, tenant_id)
            assert head is not None
            assert head.sequence_no == 2
    finally:
        if runtime_engine is not None:
            runtime_engine.dispose()
        with database.begin() as connection:
            connection.execute(text(f'DROP OWNED BY "{runtime_role}"'))
            connection.execute(text(f'DROP ROLE "{runtime_role}"'))
