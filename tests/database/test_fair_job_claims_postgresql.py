"""Real PostgreSQL proof that analysis claims take turns across organisations.

Organisation A bulk-imports 50 calls before organisation B uploads one. Claims
were first-in-first-out across all organisations, so B's call waited behind all
50. Each conversation worker now keeps one TenantTurns: B's job is claimed within
the first two claims, A keeps its own order, and provider consumers sharing the
worker never claim the same job.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.application import LOCAL_JOB
from ac_platform.conversation_intelligence.inference import INFERENCE_JOB
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.storage import PrivateLocalRecordingStorage
from ac_platform.conversation_intelligence.worker import OfflineConversationWorker
from ac_platform.outbox.models import Job, JobStatus
from ac_platform.outbox.repository import JobRepository, RecoveryStateRepository
from tests.database.test_conversation_postgresql import ActorFixture, run, seed
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness

BULK = 50


@pytest.fixture
def postgres_harness() -> Any:
    # Each test owns its queue: jobs left by another test would compete.
    yield from _postgres_harness.__wrapped__()


async def _ready(sessions: async_sessionmaker[AsyncSession], state: ActorFixture) -> int:
    actor = replace(
        state.actor,
        permissions=frozenset({"recovery_reconcile", "global_recovery_reconcile"}),
    )
    async with sessions() as database, database.begin():
        recovery = await RecoveryStateRepository(database).reconcile(
            actor=actor,
            reason="Isolated fair-claim fixture reconciliation",
            audit=AuditRepository(database),
            operations_tenant_id=state.tenant_id,
        )
        return recovery.generation


async def _queue(
    sessions: async_sessionmaker[AsyncSession],
    *,
    kind: str,
    generation: int,
    bulk_tenant: UUID,
    single_tenant: UUID,
) -> tuple[list[UUID], UUID]:
    """A's 50 jobs, then B's one, each a second newer than the one before."""

    external = kind == INFERENCE_JOB
    bulk = [uuid4() for _ in range(BULK)]
    single = uuid4()
    start = datetime.now(UTC) - timedelta(hours=1)
    rows = []
    for index, (job_id, tenant_id) in enumerate(
        [*((job_id, bulk_tenant) for job_id in bulk), (single, single_tenant)]
    ):
        created = start + timedelta(seconds=index)
        rows.append(
            {
                "id": job_id,
                "tenant_id": tenant_id,
                "kind": kind,
                "dedupe_key": f"fair-claims:{job_id}",
                "payload": {},
                "external_side_effect": external,
                "recovery_generation": generation if external else 0,
                "status": JobStatus.QUEUED.value,
                "attempt_count": 0,
                "max_attempts": 3,
                "available_at": created,
                "created_at": created,
                "updated_at": created,
            }
        )
    async with sessions() as database, database.begin():
        await database.execute(insert(Job.__table__), rows)
    return bulk, single


async def _two_orgs(postgres_harness: Any) -> tuple[Any, ActorFixture, ActorFixture, int]:
    engine = create_async_engine(postgres_harness.url, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    bulk_org, single_org = await seed(engine), await seed(engine)
    generation = await _ready(sessions, bulk_org)
    return engine, bulk_org, single_org, generation


def _local_worker(sessions: async_sessionmaker[AsyncSession], root: Path) -> Any:
    return OfflineConversationWorker(
        sessions,
        storage=PrivateLocalRecordingStorage(root / "conversation-objects"),
        scratch=PrivateLocalRecordingStorage(root / "conversation-scratch"),
        environment="test",
    )


def _provider_worker(sessions: async_sessionmaker[AsyncSession], root: Path) -> Any:
    broker: Any = object()  # claims never reach the broker; nothing is dispatched
    return ConversationInferenceWorker(
        sessions, PrivateLocalRecordingStorage(root / "provider-objects"), broker
    )


def test_local_claims_take_turns_across_organisations(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def scenario() -> None:
        engine, bulk_org, single_org, generation = await _two_orgs(postgres_harness)
        try:
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            bulk, single = await _queue(
                sessions,
                kind=LOCAL_JOB,
                generation=generation,
                bulk_tenant=bulk_org.tenant_id,
                single_tenant=single_org.tenant_id,
            )
            worker = _local_worker(sessions, tmp_path)
            claimed = [(await worker.claim()).job_id for _ in range(4)]

            assert single in claimed[:2]
            # A keeps its own queue order around B's turn.
            assert [job_id for job_id in claimed if job_id != single] == bulk[:3]
        finally:
            await engine.dispose()

    run(scenario())


def test_provider_claims_take_turns_across_organisations(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def scenario() -> None:
        engine, bulk_org, single_org, generation = await _two_orgs(postgres_harness)
        try:
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            bulk, single = await _queue(
                sessions,
                kind=INFERENCE_JOB,
                generation=generation,
                bulk_tenant=bulk_org.tenant_id,
                single_tenant=single_org.tenant_id,
            )
            # Before: plain FIFO hands A's first two jobs out and B waits for all 50.
            async with sessions() as database:
                transaction = await database.begin()
                fifo = [
                    (await JobRepository(database).claim(kinds=(INFERENCE_JOB,), limit=1))[0].id
                    for _ in range(2)
                ]
                await transaction.rollback()
            assert fifo == bulk[:2]

            worker = _provider_worker(sessions, tmp_path)
            claimed = [(await worker.claim()).job_id for _ in range(4)]

            assert single in claimed[:2]
            assert [job_id for job_id in claimed if job_id != single] == bulk[:3]
            async with sessions() as database:
                rows = (await database.scalars(select(Job).where(Job.id.in_(claimed)))).all()
            assert {row.status for row in rows} == {JobStatus.LEASED.value}
            assert {row.attempt_count for row in rows} == {1}
        finally:
            await engine.dispose()

    run(scenario())


def test_parallel_provider_consumers_share_turns_without_double_claims(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def scenario() -> None:
        engine, bulk_org, single_org, generation = await _two_orgs(postgres_harness)
        try:
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            bulk, single = await _queue(
                sessions,
                kind=INFERENCE_JOB,
                generation=generation,
                bulk_tenant=bulk_org.tenant_id,
                single_tenant=single_org.tenant_id,
            )
            # provider_consumers=3: three consumers share one worker and claim at once.
            worker = _provider_worker(sessions, tmp_path)
            together = await asyncio.gather(*(worker.claim() for _ in range(3)))
            claimed = [work.job_id for work in together]
            claimed.append((await worker.claim()).job_id)

            assert len(set(claimed)) == 4
            # A race can hand A's next job out before a turn is recorded; B
            # still goes no later than the first claim after the race.
            assert single in claimed
            assert set(claimed) - {single} == set(bulk[:3])
        finally:
            await engine.dispose()

    run(scenario())
