"""Real PostgreSQL proof for the bounded local conversation worker.

The fixtures use one-second synthetic 48 kHz WAV input and the checked-in native
AudioAtlas executable.  All storage roots and pytest scratch live outside the
repository; no provider, server, key, or paid route is activated.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import math
import struct
import threading
import wave
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence import worker as worker_module
from ac_platform.conversation_intelligence.application import (
    AUDIOATLAS_RECIPE,
)
from ac_platform.conversation_intelligence.checkpoints import SourceBinding
from ac_platform.conversation_intelligence.contracts import RunIntent
from ac_platform.conversation_intelligence.entitlements import (
    ExecutionPermission,
    MinuteAccount,
    MinuteGrant,
    Quote,
    grant_minutes,
)
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationMinuteAccount,
    ConversationPermission,
    ConversationQuote,
    ConversationRun,
)
from ac_platform.conversation_intelligence.storage import (
    ObjectKey,
    ObjectKind,
    PrivateLocalRecordingStorage,
)
from ac_platform.conversation_intelligence.worker import OfflineConversationWorker
from ac_platform.outbox.models import Job
from ac_platform.outbox.policy import ReconciliationRequiredError
from ac_platform.outbox.repository import RecoveryStateRepository
from tests.database.test_conversation_postgresql import (
    ActorFixture,
    run,
    seed,
    seed_budget,
)
from tests.database.test_conversation_postgresql import (
    application as build_application,
)
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness


@pytest.fixture
def postgres_harness() -> Any:
    # Each test gives its worker a different private storage root. Its queue
    # must be isolated too: an intentionally failed retry from an earlier test
    # can become eligible while a slower later test is running.
    yield from _postgres_harness.__wrapped__()


@dataclass(frozen=True)
class Prepared:
    state: ActorFixture
    data: bytes
    recording_id: UUID
    scope_id: UUID
    quote_id: UUID
    run_id: UUID
    worker: OfflineConversationWorker
    storage: PrivateLocalRecordingStorage
    scratch: PrivateLocalRecordingStorage


def _wav_one_second_48k() -> bytes:
    samples = bytearray()
    for index in range(48_000):
        value = int(0.25 * 32_767 * math.sin(2 * math.pi * 440 * index / 48_000))
        samples.extend(struct.pack("<h", value))
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(48_000)
        stream.writeframes(bytes(samples))
    return output.getvalue()


async def _reconcile(sessions: async_sessionmaker[AsyncSession], state: ActorFixture) -> None:
    actor = replace(
        state.actor,
        permissions=frozenset({"recovery_reconcile", "global_recovery_reconcile"}),
    )
    async with sessions() as database, database.begin():
        await RecoveryStateRepository(database).reconcile(
            actor=actor,
            reason="Isolated conversation worker fixture reconciliation",
            audit=AuditRepository(database),
            operations_tenant_id=state.tenant_id,
        )


async def _seed_minutes(
    engine: Any, state: ActorFixture, *, seconds: int = 600
) -> None:
    minutes = grant_minutes(
        MinuteAccount(str(state.tenant_id), str(state.person_id)),
        MinuteGrant(
            str(state.tenant_id),
            str(state.person_id),
            uuid4().hex,
            seconds,
            "synthetic-worker-allowance-approval",
            "authorized-fixture-admin",
            "local worker integration test",
        ),
    )
    async with AsyncSession(engine) as database, database.begin():
        database.add(
            ConversationMinuteAccount(
                tenant_id=state.tenant_id,
                person_id=state.person_id,
                snapshot=minutes.as_dict(),
                revision=1,
            )
        )


async def _add_quote(
    sessions: async_sessionmaker[AsyncSession],
    state: ActorFixture,
    recording_id: UUID,
    scope_id: UUID,
    source_sha256: str,
    *,
    now: datetime | None = None,
) -> UUID:
    quote_id = uuid4()
    # Commands in this harness use build_application(..., state)'s frozen clock.
    # A quote issued on the wall clock after a slow native run would otherwise
    # appear to be issued in the future to that same synthetic owner.
    current = now or state.now
    quoted = Quote(
        quote_id=str(quote_id),
        source=SourceBinding(
            str(state.tenant_id), str(recording_id), source_sha256, "1"
        ),
        account_id=str(state.person_id),
        budget_scope_id=str(scope_id),
        provider_id="local",
        provider_model="audioatlas",
        recipe_revision=AUDIOATLAS_RECIPE,
        operation="inspect_audioatlas",
        input_sha256=source_sha256,
        privacy_revision="synthetic-local-privacy-v1",
        permission_ref=str(state.permission_id),
        provider_terms_ref="native-source-license",
        retention_ref="delete-test-schema",
        professional_gate_ref="synthetic-fixture-only",
        pricing_ref="local-zero-price",
        entitlement_seconds=120,
        max_cost_paise=0,
        created_at_epoch=int(current.timestamp()) - 1,
        expires_at_epoch=int(current.timestamp()) + 3600,
    )
    permission = ExecutionPermission(
        "synthetic-exact-execution-approval",
        quoted.fingerprint,
        "authorized-fixture-owner",
        int(current.timestamp()) + 3600,
    )
    async with sessions() as database, database.begin():
        database.add(
            ConversationQuote(
                id=quote_id,
                tenant_id=state.tenant_id,
                person_id=state.person_id,
                recording_id=recording_id,
                budget_scope_id=scope_id,
                quote=quoted.as_dict(),
                execution_permission=permission.as_dict(),
            )
        )
    return quote_id


async def _prepare(postgres_harness: Any, tmp_path: Path) -> Prepared:
    engine = create_async_engine(postgres_harness.url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    data = _wav_one_second_48k()
    source_sha256 = hashlib.sha256(data).hexdigest()
    state = await seed(engine)
    state = replace(state, source_sha256=source_sha256)
    try:
        async with sessions() as database, database.begin():
            await database.execute(
                update(ConversationPermission)
                .where(ConversationPermission.id == state.permission_id)
                .values(source_sha256=source_sha256)
            )
        await _reconcile(sessions, state)
        storage = PrivateLocalRecordingStorage(tmp_path / "conversation-objects")
        scratch = PrivateLocalRecordingStorage(tmp_path / "conversation-scratch")
        worker = OfflineConversationWorker(
            sessions,
            storage=storage,
            scratch=scratch,
            environment="test",
        )
        recording_intent = state.recording_intent.model_copy(
            update={"source_bytes": len(data), "content_type": "audio/wav"}
        )
        async with sessions() as database, database.begin():
            registered = await build_application(database, state).register(
                state.actor,
                recording_intent,
                key=f"worker-register-{uuid4().hex}",
            )
        recording_id = UUID(registered["id"])
        async with sessions() as database, database.begin():
            stored = await build_application(database, state).store_source(
                state.actor,
                recording_id,
                chunks=(data,),
                storage=storage,
            )
        assert stored["state"] == "ready"
        scope_id = await seed_budget(engine)
        await _seed_minutes(engine, state)
        quote_id = await _add_quote(
            sessions, state, recording_id, scope_id, source_sha256
        )
        async with sessions() as database, database.begin():
            requested = await build_application(database, state).request_run(
                state.actor,
                RunIntent(
                    recording_id=recording_id,
                    source_revision="1",
                    quote_id=quote_id,
                    recipe_revision=AUDIOATLAS_RECIPE,
                ),
                key=f"worker-run-{uuid4().hex}",
            )
        return Prepared(
            state,
            data,
            recording_id,
            scope_id,
            quote_id,
            UUID(requested["id"]),
            worker,
            storage,
            scratch,
        )
    finally:
        await engine.dispose()


def _assert_scratch_empty(scratch: PrivateLocalRecordingStorage) -> None:
    assert [path.name for path in scratch.root.iterdir()] == [".ac-recording-storage"]


async def _db_run(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> ConversationRun:
    async with sessions() as database:
        run = await database.get(ConversationRun, run_id)
        assert run is not None
        return run


def test_real_worker_registers_stores_quotes_runs_native_and_settles(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        prepared = await _prepare(postgres_harness, tmp_path)
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            assert await prepared.worker.run_once()
            run = await _db_run(sessions, prepared.run_id)
            assert run.state == "completed"
            async with sessions() as database:
                checkpoints = (
                    await database.scalars(
                        select(ConversationCheckpoint)
                        .where(ConversationCheckpoint.recording_id == prepared.recording_id)
                        .order_by(ConversationCheckpoint.stage)
                    )
                ).all()
                assert [row.stage for row in checkpoints] == ["C0", "C1"]
                c0, c1 = checkpoints
                assert c0.payload is not None and c0.erased_at is None
                assert c1.payload is not None and c1.erased_at is None
                assert c1.feature_blob_id == prepared.run_id
                assert c1.payload["source_sha256"] == hashlib.sha256(prepared.data).hexdigest()
                assert c1.payload["media_duration_ms"] == 1000
                native_receipt = c1.payload["native_receipt"]
                assert len(native_receipt["source_sha256"]) == 64
                assert len(native_receipt["binary_sha256"]) == 64
                assert native_receipt["mode"] == "fft"
                assert native_receipt["rows"] == 100
                job = await database.get(Job, run.job_id)
                assert job is not None and job.status == "succeeded"
                minute = await database.get(
                    ConversationMinuteAccount,
                    (prepared.state.tenant_id, prepared.state.person_id),
                )
                assert minute is not None
                assert MinuteAccount.from_dict(minute.snapshot).available_seconds == 599
                reservation = MinuteAccount.from_dict(minute.snapshot).reservations[0]
                assert reservation.state == "settled"
                feature_sha = c1.payload["feature_sha256"]
            feature_key = ObjectKey(
                prepared.state.tenant_id,
                prepared.recording_id,
                prepared.run_id,
                ObjectKind.SIGNAL_FEATURES,
            )
            feature = b"".join(
                prepared.storage.iter_bytes(feature_key, expected_sha256=feature_sha)
            )
            assert feature.startswith(b"ACAAF001")
            _assert_scratch_empty(prepared.scratch)
        finally:
            await engine.dispose()

    run(exercise())


def test_fresh_same_recipe_quote_reuses_c1_without_extractor(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        prepared = await _prepare(postgres_harness, tmp_path)
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            assert await prepared.worker.run_once()
            fresh_quote = await _add_quote(
                sessions,
                prepared.state,
                prepared.recording_id,
                prepared.scope_id,
                hashlib.sha256(prepared.data).hexdigest(),
            )
            async with sessions() as database, database.begin():
                requested = await build_application(database, prepared.state).request_run(
                    prepared.state.actor,
                    RunIntent(
                        recording_id=prepared.recording_id,
                        source_revision="1",
                        quote_id=fresh_quote,
                        recipe_revision=AUDIOATLAS_RECIPE,
                    ),
                    key="worker-fresh-recipe-run",
                )
            second_run_id = UUID(requested["id"])

            def extractor_must_not_run(*args: Any, **kwargs: Any) -> dict[str, Any]:
                raise AssertionError("fresh same-recipe run unexpectedly re-extracted media")

            monkeypatch.setattr(worker_module, "inspect_media", extractor_must_not_run)
            assert await prepared.worker.run_once()
            run = await _db_run(sessions, second_run_id)
            assert run.state == "completed"
            async with sessions() as database:
                assert (
                    await database.scalar(
                        select(ConversationCheckpoint.id).where(
                            ConversationCheckpoint.recording_id == prepared.recording_id,
                            ConversationCheckpoint.stage == "C1",
                        )
                    )
                    is not None
                )
                minute = await database.get(
                    ConversationMinuteAccount,
                    (prepared.state.tenant_id, prepared.state.person_id),
                )
                assert minute is not None
                assert len(MinuteAccount.from_dict(minute.snapshot).reservations) == 2
                assert all(
                    reservation.state == "settled"
                    for reservation in MinuteAccount.from_dict(minute.snapshot).reservations
                )
            _assert_scratch_empty(prepared.scratch)
        finally:
            await engine.dispose()

    run(exercise())


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_cached_blob_damage_cannot_count_as_success(
    postgres_harness: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    damage: str,
) -> None:
    async def exercise() -> None:
        prepared = await _prepare(postgres_harness, tmp_path)
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            assert await prepared.worker.run_once()
            async with sessions() as database:
                first = await database.scalar(
                    select(ConversationCheckpoint).where(
                        ConversationCheckpoint.recording_id == prepared.recording_id,
                        ConversationCheckpoint.stage == "C1",
                    )
                )
                assert first is not None and first.feature_blob_id == prepared.run_id
            feature_key = ObjectKey(
                prepared.state.tenant_id,
                prepared.recording_id,
                prepared.run_id,
                ObjectKind.SIGNAL_FEATURES,
            )
            feature_path = prepared.storage._path(feature_key) / feature_key.filename
            if damage == "missing":
                assert prepared.storage.delete(feature_key)
            else:
                feature_path.write_bytes(b"damaged-feature-blob")
            fresh_quote = await _add_quote(
                sessions,
                prepared.state,
                prepared.recording_id,
                prepared.scope_id,
                hashlib.sha256(prepared.data).hexdigest(),
            )
            async with sessions() as database, database.begin():
                requested = await build_application(database, prepared.state).request_run(
                    prepared.state.actor,
                    RunIntent(
                        recording_id=prepared.recording_id,
                        source_revision="1",
                        quote_id=fresh_quote,
                        recipe_revision=AUDIOATLAS_RECIPE,
                    ),
                    key=f"worker-damaged-cache-{damage}",
                )
            second_run_id = UUID(requested["id"])

            def extractor_must_not_mask_damage(*args: Any, **kwargs: Any) -> dict[str, Any]:
                raise AssertionError("damaged cache was silently replaced by extraction")

            monkeypatch.setattr(worker_module, "inspect_media", extractor_must_not_mask_damage)
            with pytest.raises(RuntimeError, match="local conversation job failed"):
                await prepared.worker.run_once()
            run = await _db_run(sessions, second_run_id)
            assert run.state != "completed"
            async with sessions() as database:
                second_minute = await database.get(
                    ConversationMinuteAccount,
                    (prepared.state.tenant_id, prepared.state.person_id),
                )
                assert second_minute is not None
                reservations = MinuteAccount.from_dict(second_minute.snapshot).reservations
                assert len(reservations) == 2
                assert reservations[-1].state != "settled"
                assert (
                    await database.scalar(
                        select(Job.status).where(Job.id == run.job_id)
                    )
                    != "succeeded"
                )
            _assert_scratch_empty(prepared.scratch)
        finally:
            await engine.dispose()

    run(exercise())


def test_post_c0_crash_then_expired_lease_retries_exact_attempt(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        prepared = await _prepare(postgres_harness, tmp_path)
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            def crash_after_c0(*args: Any, **kwargs: Any) -> dict[str, Any]:
                raise RuntimeError("synthetic post-C0 worker crash")

            original_inspect = prepared.worker._inspect
            monkeypatch.setattr(prepared.worker, "_inspect", crash_after_c0)
            with pytest.raises(RuntimeError, match="local conversation job failed"):
                await prepared.worker.run_once()
            monkeypatch.setattr(prepared.worker, "_inspect", original_inspect)
            async with sessions() as database:
                c0 = await database.scalar(
                    select(ConversationCheckpoint).where(
                        ConversationCheckpoint.recording_id == prepared.recording_id,
                        ConversationCheckpoint.stage == "C0",
                    )
                )
                assert c0 is not None and c0.payload is not None
                run = await database.get(ConversationRun, prepared.run_id)
                assert run is not None and run.state != "completed"
                job = await database.get(Job, run.job_id)
                assert job is not None and job.status == "retry_wait"
            async with sessions() as database, database.begin():
                await database.execute(
                    update(Job)
                    .where(Job.id == job.id)
                    .values(available_at=datetime.now(UTC) - timedelta(seconds=1))
                )
            stale = await prepared.worker.claim()
            assert stale is not None
            with postgres_harness.begin() as connection:
                connection.execute(
                    update(Job)
                    .where(Job.id == stale.job_id)
                    .values(leased_until=datetime.now(UTC) - timedelta(seconds=1))
                )
            assert await prepared.worker.run_once()
            run = await _db_run(sessions, prepared.run_id)
            assert run.state == "completed"
            async with sessions() as database:
                final_job = await database.get(Job, run.job_id)
                assert final_job is not None and final_job.status == "succeeded"
                assert final_job.attempt_count >= 3
            _assert_scratch_empty(prepared.scratch)
        finally:
            await engine.dispose()

    run(exercise())


@pytest.mark.parametrize("race", ["deletion", "revocation"])
def test_deletion_and_revocation_races_fence_publication_and_clean_scratch(
    postgres_harness: Any, tmp_path: Path, race: str
) -> None:
    async def exercise() -> None:
        prepared = await _prepare(postgres_harness, tmp_path)
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        started, release = threading.Event(), threading.Event()
        original = prepared.worker._inspect

        def blocked_extract(
            source: ObjectKey, sha: str, expected_bytes: int, root: Path
        ) -> dict[str, Any]:
            started.set()
            if not release.wait(10):
                raise RuntimeError("race fixture timed out")
            return original(source, sha, expected_bytes, root)

        prepared.worker._inspect = blocked_extract
        task = asyncio.create_task(prepared.worker.run_once())
        try:
            assert await asyncio.to_thread(started.wait, 10)
            async with sessions() as database, database.begin():
                if race == "deletion":
                    deleted = await build_application(database, prepared.state).request_deletion(
                        prepared.state.actor,
                        prepared.recording_id,
                        key="worker-race-delete",
                    )
                    assert deleted["state"] == "deleting"
                else:
                    await database.execute(
                        update(ConversationPermission)
                        .where(ConversationPermission.id == prepared.state.permission_id)
                        .values(revoked_at=datetime.now(UTC))
                    )
            release.set()
            with pytest.raises(RuntimeError, match="local conversation job failed"):
                await task
            _assert_scratch_empty(prepared.scratch)
            async with sessions() as database:
                assert (
                    await database.scalar(
                        select(ConversationCheckpoint.id).where(
                            ConversationCheckpoint.recording_id == prepared.recording_id,
                            ConversationCheckpoint.stage == "C1",
                        )
                    )
                    is None
                )
                run = await database.get(ConversationRun, prepared.run_id)
                assert run is not None and run.state != "completed"
            if race == "deletion":
                assert await prepared.worker.run_once()
                assert prepared.storage.list_recording(
                    prepared.state.tenant_id, prepared.recording_id
                ) == ()
                _assert_scratch_empty(prepared.scratch)
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await engine.dispose()

    run(exercise())


def test_recovery_generation_mismatch_is_fenced_then_reconciled_retry_succeeds(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        prepared = await _prepare(postgres_harness, tmp_path)
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            work = await prepared.worker.claim()
            assert work is not None
            async with sessions() as database, database.begin():
                held = await RecoveryStateRepository(database).mark_restore(
                    reason="Synthetic recovery generation mismatch fixture"
                )
                assert held.status == "held"
                assert held.generation == work.recovery_generation + 1
            with pytest.raises(ReconciliationRequiredError):
                await prepared.worker._inspect_job(work)
            actor = replace(
                prepared.state.actor,
                permissions=frozenset({"recovery_reconcile", "global_recovery_reconcile"}),
            )
            async with sessions() as database, database.begin():
                ready = await RecoveryStateRepository(database).reconcile(
                    actor=actor,
                    reason="Synthetic recovery generation mismatch reconciled",
                    audit=AuditRepository(database),
                    operations_tenant_id=prepared.state.tenant_id,
                )
                assert ready.status == "ready"
                assert ready.generation == work.recovery_generation + 1
            with postgres_harness.begin() as connection:
                connection.execute(
                    update(Job)
                    .where(Job.id == work.job_id)
                    .values(leased_until=datetime.now(UTC) - timedelta(seconds=1))
                )
            assert await prepared.worker.run_once()
            run = await _db_run(sessions, prepared.run_id)
            assert run.state == "completed"
            _assert_scratch_empty(prepared.scratch)
        finally:
            await engine.dispose()

    run(exercise())
