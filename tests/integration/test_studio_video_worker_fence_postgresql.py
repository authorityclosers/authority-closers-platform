"""PostgreSQL proof for the Studio worker's internal lease/recovery fence."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.engine import URL, Engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from ac_platform.identity.models import Person
from ac_platform.media.studio_video_completion import MEDIA_PROCESS_VERSION_JOB
from ac_platform.outbox.errors import LeaseLostError
from ac_platform.outbox.models import Job, JobStatus, OperationsRecoveryState, RecoveryStatus
from ac_platform.outbox.policy import ReconciliationRequiredError
from ac_platform.outbox.repository import JobRepository
from tests.integration.test_media_delivery_renewal_postgresql import _postgres_url
from tests.integration.test_media_delivery_renewal_postgresql import (
    postgres_harness as postgres_harness,  # noqa: F401 - isolated schema fixture
)


def _run_async[T](coroutine: Coroutine[Any, Any, T]) -> T:
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


@pytest.fixture(scope="module")
def studio_worker_fence_postgres_harness(request: pytest.FixtureRequest) -> object:
    url = _postgres_url()
    if (
        url.host != "127.0.0.1"
        or url.port != 55432
        or url.database != "ac_local_sandbox"
        or url.username != "ac_owner"
        or url.query
    ):
        pytest.fail("Studio worker fencing requires the explicit local PostgreSQL target")
    return request.getfixturevalue("postgres_harness")


def _seed(engine: Engine) -> tuple[int, UUID, dict[str, tuple[UUID, UUID]]]:
    now = datetime.now(UTC)
    operator_id = uuid4()
    generation = 9
    jobs = {
        name: (uuid4(), uuid4())
        for name in ("live", "expired", "external", "other_kind", "reclaimed")
    }
    with Session(engine) as database:
        database.add(
            Person(
                id=operator_id,
                email=f"studio-worker-fence-{operator_id.hex}@example.test",
                status="active",
            )
        )
        state = database.get(OperationsRecoveryState, 1)
        assert state is not None
        state.generation = generation
        state.status = RecoveryStatus.READY.value
        state.marked_at = now
        state.hold_reason = "worker fence fixture"
        state.reconciled_at = now
        state.reconciled_by = operator_id
        state.reconciliation_reason = "worker fence fixture ready"
        for name, (job_id, token) in jobs.items():
            external = name == "external"
            database.add(
                Job(
                    id=job_id,
                    kind=(
                        "email.not-the-studio-worker.v1"
                        if name == "other_kind"
                        else MEDIA_PROCESS_VERSION_JOB
                    ),
                    dedupe_key=f"studio-worker-fence:{job_id}",
                    payload={},
                    external_side_effect=external,
                    recovery_generation=generation if external else 0,
                    status=JobStatus.LEASED.value,
                    attempt_count=1,
                    max_attempts=3,
                    available_at=now,
                    leased_until=(
                        now - timedelta(seconds=1)
                        if name == "expired"
                        else now + timedelta(minutes=5)
                    ),
                    lease_token=token,
                    created_at=now,
                    updated_at=now,
                )
            )
        database.commit()
    return generation, operator_id, jobs


def test_postgresql_internal_worker_fence_rejects_stale_or_noncanonical_lease(
    studio_worker_fence_postgres_harness: object,
) -> None:
    harness = cast(Any, studio_worker_fence_postgres_harness)
    assert hasattr(harness, "schema_url") and isinstance(harness.schema_url, URL)
    generation, operator_id, jobs = _seed(harness.engine)

    async def scenario() -> None:
        engine = create_async_engine(
            harness.schema_url,
            pool_size=2,
            max_overflow=0,
            hide_parameters=True,
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with sessions() as database, database.begin():
                live_id, live_token = jobs["live"]
                row = await JobRepository(database).lock_internal_lease(
                    live_id,
                    live_token,
                    kind=MEDIA_PROCESS_VERSION_JOB,
                    recovery_generation=generation,
                )
                assert row.id == live_id

            for name in ("expired", "external", "other_kind"):
                async with sessions() as database, database.begin():
                    job_id, token = jobs[name]
                    with pytest.raises(LeaseLostError):
                        await JobRepository(database).lock_internal_lease(
                            job_id,
                            token,
                            kind=MEDIA_PROCESS_VERSION_JOB,
                            recovery_generation=generation,
                        )

            reclaimed_id, old_token = jobs["reclaimed"]
            async with sessions() as database, database.begin():
                reclaimed = await database.get(Job, reclaimed_id, with_for_update=True)
                assert reclaimed is not None
                reclaimed.lease_token = uuid4()
            async with sessions() as database, database.begin():
                with pytest.raises(LeaseLostError):
                    await JobRepository(database).lock_internal_lease(
                        reclaimed_id,
                        old_token,
                        kind=MEDIA_PROCESS_VERSION_JOB,
                        recovery_generation=generation,
                    )

            async with sessions() as database, database.begin():
                state = await database.get(OperationsRecoveryState, 1, with_for_update=True)
                assert state is not None
                state.status = RecoveryStatus.HELD.value
                state.reconciled_at = state.reconciled_by = state.reconciliation_reason = None
            async with sessions() as database, database.begin():
                with pytest.raises(ReconciliationRequiredError, match="held"):
                    await JobRepository(database).lock_internal_lease(
                        live_id,
                        live_token,
                        kind=MEDIA_PROCESS_VERSION_JOB,
                        recovery_generation=generation,
                    )

            async with sessions() as database, database.begin():
                state = await database.get(OperationsRecoveryState, 1, with_for_update=True)
                assert state is not None
                state.status = RecoveryStatus.READY.value
                state.generation += 1
                state.reconciled_at = datetime.now(UTC)
                state.reconciled_by = operator_id
                state.reconciliation_reason = "new generation ready"
            async with sessions() as database, database.begin():
                with pytest.raises(ReconciliationRequiredError, match="stale"):
                    await JobRepository(database).lock_internal_lease(
                        live_id,
                        live_token,
                        kind=MEDIA_PROCESS_VERSION_JOB,
                        recovery_generation=generation,
                    )
        finally:
            await engine.dispose()

    _run_async(scenario())
