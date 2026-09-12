"""Real PostgreSQL proof that workers cannot claim another worker's jobs.

The imported harness creates a random schema before running Alembic, because
the migrator is not allowed to create schemas. The only permitted connection
target is the disposable local owner database at 127.0.0.1:55432.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import insert, select
from sqlalchemy.engine import URL, Engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from ac_platform.identity.models import Person
from ac_platform.outbox.models import Job, JobStatus, OperationsRecoveryState, RecoveryStatus
from ac_platform.outbox.repository import JobRepository, build_job_take_statement
from ac_platform.worker import ENROLLMENT_WELCOME_JOB
from tests.integration.test_media_delivery_renewal_postgresql import _postgres_url
from tests.integration.test_media_delivery_renewal_postgresql import (
    postgres_harness as postgres_harness,  # noqa: F401 - isolated schema fixture
)

MEDIA_PROCESS_VERSION_JOB = "media.process_version.v1"


def _run_async[T](coroutine):
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


@pytest.fixture(scope="module")
def job_kind_postgres_harness(request) -> object:
    url = _postgres_url()
    if (
        url.host != "127.0.0.1"
        or url.port != 55432
        or url.database != "ac_local_sandbox"
        or url.username != "ac_owner"
        or url.query
    ):
        pytest.fail("job-kind isolation requires the explicit local ac_owner PostgreSQL target")
    return request.getfixturevalue("postgres_harness")


def _seed_jobs(engine: Engine) -> dict[str, UUID]:
    operator_id = uuid4()
    email_first_id, media_first_id = uuid4(), uuid4()
    email_second_id, media_second_id = uuid4(), uuid4()
    now = datetime.now(UTC)
    with Session(engine) as database:
        database.execute(
            insert(Person.__table__).values(
                id=operator_id,
                email=f"job-kind-isolation-{operator_id.hex}@example.test",
                status="active",
            )
        )
        state = database.get(OperationsRecoveryState, 1)
        assert state is not None
        state.status = RecoveryStatus.READY.value
        state.reconciled_at = now
        state.reconciled_by = operator_id
        state.reconciliation_reason = "job-kind isolation test ready"

        rows = []
        for offset, job_id, kind, external_side_effect in (
            (0, email_first_id, ENROLLMENT_WELCOME_JOB, True),
            (1, media_first_id, MEDIA_PROCESS_VERSION_JOB, False),
            (2, email_second_id, ENROLLMENT_WELCOME_JOB, True),
            (3, media_second_id, MEDIA_PROCESS_VERSION_JOB, False),
        ):
            created_at = now + timedelta(seconds=offset)
            rows.append(
                {
                    "id": job_id,
                    "kind": kind,
                    "dedupe_key": f"job-kind-isolation:{job_id}",
                    "payload": {},
                    "external_side_effect": external_side_effect,
                    "recovery_generation": state.generation if external_side_effect else 0,
                    "status": JobStatus.QUEUED.value,
                    "attempt_count": 0,
                    "max_attempts": 3,
                    "available_at": now - timedelta(minutes=1),
                    "created_at": created_at,
                    "updated_at": created_at,
                }
            )
        database.execute(insert(Job.__table__), rows)
        database.commit()
    return {
        "email_first": email_first_id,
        "media_first": media_first_id,
        "email_second": email_second_id,
        "media_second": media_second_id,
    }


def test_postgresql_workers_claim_only_their_allowlisted_kinds(
    job_kind_postgres_harness,
) -> None:
    harness = job_kind_postgres_harness
    assert hasattr(harness, "schema_url")
    schema_url = harness.schema_url
    assert isinstance(schema_url, URL)
    ids = _seed_jobs(harness.engine)

    async def scenario() -> None:
        engine = create_async_engine(schema_url, pool_size=2, max_overflow=0, hide_parameters=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with sessions() as database, database.begin():
                claimed = await JobRepository(database).claim(
                    kinds=(ENROLLMENT_WELCOME_JOB,),
                    lease_for=timedelta(seconds=30),
                    limit=1,
                )
                assert [job.id for job in claimed] == [ids["email_first"]]

            async with sessions() as database, database.begin():
                untouched = await database.get(Job, ids["media_first"])
                assert untouched is not None
                assert untouched.status == JobStatus.QUEUED.value
                assert untouched.attempt_count == 0
                rejected = await database.execute(
                    build_job_take_statement(
                        job_id=ids["media_first"],
                        lease_token=uuid4(),
                        lease_for=timedelta(seconds=30),
                        recovery_generation=(
                            await database.scalar(
                                select(OperationsRecoveryState.generation).where(
                                    OperationsRecoveryState.id == 1
                                )
                            )
                        ),
                        kinds=(ENROLLMENT_WELCOME_JOB,),
                    )
                )
                assert rejected.rowcount == 0
                await database.refresh(untouched)
                assert untouched.status == JobStatus.QUEUED.value
                assert untouched.attempt_count == 0

            async with sessions() as database, database.begin():
                claimed = await JobRepository(database).claim(
                    kinds=(MEDIA_PROCESS_VERSION_JOB,),
                    lease_for=timedelta(seconds=30),
                    limit=1,
                )
                assert [job.id for job in claimed] == [ids["media_first"]]
                untouched = await database.get(Job, ids["email_second"])
                assert untouched is not None
                assert untouched.status == JobStatus.QUEUED.value
                assert untouched.attempt_count == 0

            async with sessions() as database:
                rows = {
                    row.id: row
                    for row in (
                        await database.scalars(select(Job).where(Job.id.in_(tuple(ids.values()))))
                    ).all()
                }
                assert rows[ids["email_first"]].status == JobStatus.LEASED.value
                assert rows[ids["email_first"]].attempt_count == 1
                assert rows[ids["media_first"]].status == JobStatus.LEASED.value
                assert rows[ids["media_first"]].attempt_count == 1
                for name in ("email_second", "media_second"):
                    assert rows[ids[name]].status == JobStatus.QUEUED.value
                    assert rows[ids[name]].attempt_count == 0
        finally:
            await engine.dispose()

    _run_async(scenario())
