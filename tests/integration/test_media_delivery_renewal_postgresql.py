"""Real PostgreSQL proof that concurrent delivery renewal appends one shared grant."""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import sys
from collections.abc import Coroutine, Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.catalog.models import Activity, Module, Program, ProgramVersion
from ac_platform.catalog.services import CatalogService, SqlAlchemyCatalogStore
from ac_platform.enrollment.models import (
    CommandIdempotency,
    Enrollment,
    EnrollmentProvenance,
    Entitlement,
)
from ac_platform.http.learning import _default_activity_resolver
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.learning.models import PlaybackSession
from ac_platform.learning.services import (
    ActivityDefinition,
    LearningAccessContext,
    LearningCommandBundle,
    PlaybackSessionSnapshot,
    SqlAlchemyLearningRepository,
    VideoCoverage,
    VideoEvidencePolicy,
    WatchIntervalSnapshot,
)
from ac_platform.media.api_contracts import (
    ActivityMediaBindingRequest,
    ActivityMediaDescriptorResponse,
)
from ac_platform.media.bindings import resolve_activity_media_binding_for_learning
from ac_platform.media.models import (
    MediaAsset,
    MediaCaptionTrack,
    MediaPlaybackGrant,
    MediaRendition,
    MediaVersion,
)
from ac_platform.media.policy import SignedMediaDeliveryPort
from ac_platform.media.service import MediaService
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import InMemoryPrivateObjectStorage
from ac_platform.tenancy.models import Membership, Tenant

NOW = datetime(2026, 9, 8, 12, tzinfo=UTC)
DELIVERY_TTL = timedelta(seconds=300)
RENEWAL_MARGIN = timedelta(seconds=30)
STABLE_SCOPE_FIELDS = (
    "tenant_id",
    "person_id",
    "session_id",
    "activity_id",
    "activity_version",
    "asset_id",
    "version_id",
    "enrollment_id",
    "binding_id",
)


@dataclass(frozen=True, slots=True)
class _Harness:
    engine: Engine
    schema_url: URL


@dataclass(frozen=True, slots=True)
class _Seed:
    actor: ActorContext
    enrollment_id: UUID
    program_version_id: UUID
    activity_id: UUID


def _run_async[T](coroutine: Coroutine[Any, Any, T]) -> T:
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


def _postgres_url() -> URL:
    raw = os.getenv("AC_MEDIA_DELIVERY_RENEWAL_POSTGRES_TEST_URL") or os.getenv(
        "AC_TEST_DATABASE_URL"
    )
    if not raw:
        if os.getenv("AC_REQUIRE_MEDIA_DELIVERY_RENEWAL_POSTGRES_TEST") == "1":
            pytest.fail("media delivery renewal PostgreSQL URL is required but not configured")
        pytest.skip("media delivery renewal PostgreSQL URL is not configured")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql":
        pytest.fail("media delivery renewal integration requires PostgreSQL")
    if url.host not in {None, "127.0.0.1", "localhost", "::1"}:
        pytest.fail("media delivery renewal test refuses a non-local PostgreSQL database")
    return url.set(drivername="postgresql+psycopg")


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[_Harness]:
    root = Path(__file__).resolve().parents[2]
    base_url = _postgres_url()
    schema = f"media_delivery_renewal_{uuid4().hex}"
    admin_engine = create_engine(base_url, pool_pre_ping=True)
    schema_engine: Engine | None = None
    created = False
    try:
        with admin_engine.begin() as connection:
            connection.execute(CreateSchema(schema))
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
                        str(root / "packages" / "python"),
                        environment.get("PYTHONPATH", ""),
                    )
                    if part
                ),
            }
        )
        migration = subprocess.run(  # noqa: S603 - fixed local Alembic command
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if migration.returncode != 0:
            # Connection details and migration output may contain credentials.
            pytest.fail("fresh isolated media delivery renewal PostgreSQL migration failed")
        schema_engine = create_engine(schema_url, pool_pre_ping=True)
        yield _Harness(engine=schema_engine, schema_url=schema_url)
    finally:
        if schema_engine is not None:
            schema_engine.dispose()
        if created:
            with admin_engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
        admin_engine.dispose()


def _service(now: datetime, *, delivery_ttl: timedelta = DELIVERY_TTL) -> MediaService:
    signer = MediaSigner("media-renewal-isolated-test-key-32bytes")
    service = MediaService(
        storage=InMemoryPrivateObjectStorage(signer),
        signer=signer,
        webhook_secret="media-renewal-test-webhook-32bytes",  # noqa: S106 - isolated test key
        delivery_port=SignedMediaDeliveryPort(
            signer=signer,
            delivery_origin="https://app.test",
            playback_ttl=delivery_ttl,
        ),
        delivery_activity_resolver=_default_activity_resolver,
    )
    service._now = lambda: now
    return service


def _seed(engine: Engine) -> _Seed:
    tenant_id, person_id, identity_id, owner_id = (uuid4() for _ in range(4))
    program_id, version_id, module_id, activity_id = (uuid4() for _ in range(4))
    enrollment_id, provenance_id, command_id, entitlement_id = (uuid4() for _ in range(4))
    asset_id, media_version_id = uuid4(), uuid4()
    actor = ActorContext(person_id, identity_id, tenant_id)
    catalog_scope = {"scope": "tenant", "owner_key": tenant_id, "tenant_id": tenant_id}
    version_scope = {
        **catalog_scope,
        "program_id": program_id,
        "program_version_id": version_id,
    }
    enrollment_scope = {
        "tenant_id": tenant_id,
        "program_version_id": version_id,
        "program_id": program_id,
        "program_scope": "tenant",
        "program_tenant_id": tenant_id,
        "program_owner_key": tenant_id,
    }
    prefix = f"tenants/{tenant_id}/media/video/{asset_id}/{media_version_id}"
    with Session(engine) as database:
        database.add_all(
            [
                Tenant(id=tenant_id, slug=f"renewal-{tenant_id.hex}", name="Renewal test tenant"),
                Person(id=person_id, email=f"learner-{person_id.hex}@example.test"),
                Person(id=owner_id, email=f"owner-{owner_id.hex}@example.test"),
            ]
        )
        database.flush()
        database.add_all(
            [
                Membership(tenant_id=tenant_id, person_id=person_id, role="learner"),
                Membership(tenant_id=tenant_id, person_id=owner_id, role="owner"),
                Program(
                    id=program_id,
                    slug=f"renewal-{program_id.hex}",
                    title="Delivery renewal test program",
                    **catalog_scope,
                ),
            ]
        )
        database.flush()
        version = ProgramVersion(
            id=version_id,
            program_id=program_id,
            version_number=1,
            status="draft",
            **catalog_scope,
        )
        database.add_all(
            [
                version,
                IdentitySession(
                    id=identity_id,
                    person_id=person_id,
                    token_hash=hashlib.sha256(identity_id.bytes).digest(),
                    selected_tenant_id=tenant_id,
                    created_at=NOW - timedelta(minutes=1),
                    expires_at=NOW + timedelta(hours=1),
                ),
            ]
        )
        database.flush()
        database.add(
            Module(id=module_id, position=1, title="Test-only media module", **version_scope)
        )
        database.flush()
        database.add(
            Activity(
                id=activity_id,
                module_id=module_id,
                position=1,
                kind="VIDEO",
                title="Synthetic delivery fixture",
                prompt="Test media delivery without an evidence policy.",
                **version_scope,
            )
        )
        database.flush()
        catalog_store = SqlAlchemyCatalogStore(database)
        catalog = CatalogService(catalog_store, clock=lambda: NOW)
        snapshot = catalog_store.get_version(version_id)
        assert snapshot is not None
        version.content_digest = catalog._canonical_content_digest(snapshot)
        version.content_source_ref = __file__
        version.content_reviewed_by = "integration-reviewer@example.test"
        version.content_reviewed_at = NOW
        version.release_id = "d" * 40
        version.content_seed_kind = "reviewed"
        database.flush()
        catalog.publish_version(version_id, tenant_id=tenant_id, now=NOW)

        database.add(
            Enrollment(
                id=enrollment_id,
                person_id=person_id,
                source="free_self",
                status="active",
                enrolled_at=NOW,
                **enrollment_scope,
            )
        )
        database.flush()
        command = CommandIdempotency(
            id=command_id,
            actor_person_id=person_id,
            subject_person_id=person_id,
            operation="enroll_free",
            idempotency_key="seed-renewal-enrollment",
            request_digest=hashlib.sha256(b"seed-renewal-enrollment").hexdigest(),
            status="pending",
            **enrollment_scope,
        )
        database.add(command)
        database.flush()
        database.add(
            EnrollmentProvenance(
                id=provenance_id,
                enrollment_id=enrollment_id,
                person_id=person_id,
                actor_person_id=person_id,
                command_idempotency_id=command_id,
                source="free_self",
                audit_event_name="audit.enrollment.created.v1",
                policy_inputs={},
                controlled_gaps=[],
                **enrollment_scope,
            )
        )
        database.flush()
        database.add(
            Entitlement(
                id=entitlement_id,
                person_id=person_id,
                enrollment_id=enrollment_id,
                provenance_id=provenance_id,
                status="active",
                granted_at=NOW,
                **enrollment_scope,
            )
        )
        database.flush()
        command.status = "completed"
        command.result_enrollment_id = enrollment_id
        command.result_entitlement_id = entitlement_id
        command.result_provenance_id = provenance_id
        command.completed_at = NOW
        asset = MediaAsset(
            id=asset_id,
            tenant_id=tenant_id,
            owner_person_id=owner_id,
            purpose="video",
            state="ready",
        )
        database.add(asset)
        database.flush()
        database.add(
            MediaVersion(
                id=media_version_id,
                tenant_id=tenant_id,
                asset_id=asset_id,
                version_number=1,
                purpose="video",
                state="ready",
                content_type="video/mp4",
                declared_bytes=10,
                actual_bytes=10,
                object_key=f"{prefix}/original",
                duration_seconds=12,
                width=1920,
                height=1080,
            )
        )
        database.flush()
        asset.current_version_id = media_version_id
        database.add_all(
            [
                MediaRendition(
                    tenant_id=tenant_id,
                    asset_id=asset_id,
                    version_id=media_version_id,
                    protocol="progressive",
                    content_type="video/mp4",
                    object_key=f"{prefix}/renditions/1080p.mp4",
                    width=1920,
                    height=1080,
                ),
                MediaCaptionTrack(
                    tenant_id=tenant_id,
                    version_id=media_version_id,
                    language="en",
                    kind="captions",
                    state="ready",
                    content_type="text/vtt",
                    object_key=f"{prefix}/captions/en.vtt",
                    is_default=True,
                ),
            ]
        )
        database.flush()
        _service(NOW).bind_activity_media(
            database,
            replace(actor, permissions=frozenset({"catalog_write"})),
            ActivityMediaBindingRequest(
                activity_id=activity_id,
                module_id=module_id,
                program_version_id=version_id,
                program_id=program_id,
                program_scope="tenant",
                program_owner_key=tenant_id,
                asset_id=asset_id,
                version_id=media_version_id,
                approval_reference="TEST-ONLY-APPROVED-FIXTURE",
            ),
            idempotency_key="renewal-test-activity-binding",
        )
        database.commit()
    return _Seed(actor, enrollment_id, version_id, activity_id)


def _access(database: Session, seed: _Seed) -> LearningAccessContext:
    store = SqlAlchemyLearningRepository(
        database,
        activity_resolver=_default_activity_resolver,
        reviewer_resolver=lambda _access: None,
        activity_media_resolver=resolve_activity_media_binding_for_learning,
    )
    assert seed.actor.tenant_id is not None
    return store.resolve_access(
        actor=seed.actor,
        tenant_id=seed.actor.tenant_id,
        enrollment_id=seed.enrollment_id,
        program_version_id=seed.program_version_id,
        activity_id=seed.activity_id,
    )


async def _descriptor(
    database: AsyncSession,
    seed: _Seed,
    now: datetime,
    *,
    delivery_ttl: timedelta = DELIVERY_TTL,
) -> ActivityMediaDescriptorResponse:
    access = await database.run_sync(lambda sync: _access(sync, seed))
    result = await _service(
        now, delivery_ttl=delivery_ttl
    ).resolve_activity_media_descriptor_for_learner(database, seed.actor, access)
    assert result.playback_available
    assert result.delivery is not None and result.delivery.progressive_url is not None
    return result


def _claims(url: str | None, now: datetime) -> dict[str, Any]:
    assert url is not None
    token = parse_qs(urlsplit(url).query)["token"][0]
    return _service(now).signer.verify(token, token_type="playback", now=now)  # noqa: S106


async def _transaction_timeouts(database: AsyncSession) -> int:
    await database.execute(text("SET LOCAL lock_timeout = '10s'"))
    await database.execute(text("SET LOCAL statement_timeout = '15s'"))
    pid = await database.scalar(select(func.pg_backend_pid()))
    assert isinstance(pid, int)
    return pid


def test_concurrent_renewal_waits_for_commit_then_reuses_one_same_scope_grant(
    postgres_harness: _Harness,
) -> None:
    seed = _seed(postgres_harness.engine)

    async def scenario() -> None:
        engine = create_async_engine(postgres_harness.schema_url, pool_size=4, max_overflow=0)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with sessions() as database, database.begin():
                original = await _descriptor(database, seed, NOW)
                assert original.delivery is not None
                original_claims = _claims(original.delivery.progressive_url, NOW)
                old_id = UUID(original_claims["delivery_grant_id"])
                old_grant = await database.get(MediaPlaybackGrant, old_id)
                assert old_grant is not None
                predecessor = {
                    column.name: getattr(old_grant, column.name)
                    for column in MediaPlaybackGrant.__table__.columns
                }
                renewal_time = old_grant.expires_at - RENEWAL_MARGIN
                assert old_grant.expires_at - old_grant.created_at == DELIVERY_TTL

            first_issued = asyncio.Event()
            second_started = asyncio.Event()
            release_first = asyncio.Event()
            backend_pids: dict[str, int] = {}

            async def first_request() -> ActivityMediaDescriptorResponse:
                async with sessions() as database, database.begin():
                    backend_pids["first"] = await _transaction_timeouts(database)
                    result = await _descriptor(database, seed, renewal_time)
                    first_issued.set()
                    await asyncio.wait_for(release_first.wait(), timeout=8)
                return result

            async def second_request() -> ActivityMediaDescriptorResponse:
                await asyncio.wait_for(first_issued.wait(), timeout=8)
                async with sessions() as database, database.begin():
                    backend_pids["second"] = await _transaction_timeouts(database)
                    second_started.set()
                    return await _descriptor(database, seed, renewal_time)

            first_task = asyncio.create_task(first_request())
            second_task = asyncio.create_task(second_request())
            try:
                await asyncio.wait_for(second_started.wait(), timeout=8)
                async with sessions() as observer:
                    async with asyncio.timeout(5):
                        while True:
                            blockers = await observer.scalar(
                                select(func.pg_blocking_pids(backend_pids["second"]))
                            )
                            if backend_pids["first"] in blockers:
                                break
                            # A missing lock must fail, even if timing would otherwise let
                            # both requests observe the same already-committed replacement.
                            if second_task.done():
                                await second_task
                                pytest.fail("concurrent renewal did not wait for the first grant")
                            await asyncio.sleep(0.01)
                    assert not second_task.done()
                    visible_grants = (
                        await observer.scalars(
                            select(MediaPlaybackGrant).where(
                                MediaPlaybackGrant.tenant_id == seed.actor.tenant_id
                            )
                        )
                    ).all()
                    assert [grant.id for grant in visible_grants] == [old_id]
                release_first.set()
                first, second = await asyncio.wait_for(
                    asyncio.gather(first_task, second_task), timeout=8
                )
            finally:
                release_first.set()
                for task in (first_task, second_task):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(first_task, second_task, return_exceptions=True)

            assert first.delivery is not None and second.delivery is not None
            renewed_claims = _claims(first.delivery.progressive_url, renewal_time)
            second_claims = _claims(second.delivery.progressive_url, renewal_time)
            renewed_id = UUID(renewed_claims["delivery_grant_id"])
            assert renewed_id != old_id
            assert second_claims["delivery_grant_id"] == str(renewed_id)
            for name in STABLE_SCOPE_FIELDS:
                assert renewed_claims[name] == second_claims[name] == original_claims[name]
            for result in (first, second):
                caption_claims = _claims(result.captions[0].source_url, renewal_time)
                for name in (*STABLE_SCOPE_FIELDS, "delivery_grant_id", "iat", "exp"):
                    assert caption_claims[name] == second_claims[name] == renewed_claims[name]
            assert renewed_claims["iat"] == int(renewal_time.timestamp())
            assert renewed_claims["exp"] - renewed_claims["iat"] == 300

            async with sessions() as database:
                grants = (
                    await database.scalars(
                        select(MediaPlaybackGrant).where(
                            MediaPlaybackGrant.tenant_id == seed.actor.tenant_id
                        )
                    )
                ).all()
                assert {grant.id for grant in grants} == {old_id, renewed_id}
                old_grant = await database.get(MediaPlaybackGrant, old_id)
                renewed_grant = await database.get(MediaPlaybackGrant, renewed_id)
                assert old_grant is not None and renewed_grant is not None
                assert {
                    column.name: getattr(old_grant, column.name)
                    for column in MediaPlaybackGrant.__table__.columns
                } == predecessor
                assert renewed_grant.request_fingerprint == old_grant.request_fingerprint
                assert renewed_grant.expires_at - renewed_grant.created_at == DELIVERY_TTL
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(PlaybackSession)
                        .where(PlaybackSession.tenant_id == seed.actor.tenant_id)
                    )
                    == 0
                )
                events = (
                    await database.scalars(
                        select(AuditEvent)
                        .where(AuditEvent.tenant_id == seed.actor.tenant_id)
                        .order_by(AuditEvent.sequence_no)
                    )
                ).all()
                assert len(events) == 2
                assert {event.resource_id for event in events} == {str(old_id), str(renewed_id)}
                assert all(event.session_id == seed.actor.session_id for event in events)
                assert all(event.action == "media.activity_delivery_granted" for event in events)
                assert all(event.resource_type == "media_playback_grant" for event in events)
                assert events[1].payload["predecessor_grant_id"] == str(old_id)
                assert (await AuditRepository(database).verify(seed.actor.tenant_id)).valid
        finally:
            await engine.dispose()

    _run_async(scenario())


def test_delivery_renewal_preserves_real_evidence_session_and_accumulated_coverage(
    postgres_harness: _Harness,
) -> None:
    seed = _seed(postgres_harness.engine)
    # This policy exists only in this isolated test composition. It does not
    # activate a reviewed evidence policy for local films or any deployed runtime.
    policy = VideoEvidencePolicy(
        version="TEST-ONLY-delivery-renewal-evidence-continuity-v1",
        coverage_threshold=0.9,
        session_ttl_seconds=60,
        future_clock_skew_seconds=0,
        minimum_watch_interval_seconds=1,
        max_event_seconds=10,
        max_heartbeat_gap_seconds=15,
        minimum_heartbeats_for_completion=2,
        clock_grace_seconds=0,
        max_rewind_seconds=2,
    )
    test_delivery_ttl = timedelta(seconds=10)
    scope = {
        "actor": seed.actor,
        "tenant_id": seed.actor.tenant_id,
        "enrollment_id": seed.enrollment_id,
        "program_version_id": seed.program_version_id,
        "activity_id": seed.activity_id,
    }

    def evidence_activity(row: object, version: object) -> ActivityDefinition:
        return replace(_default_activity_resolver(row, version), policy_version=policy.version)

    def commands(database: Session, now: datetime) -> LearningCommandBundle:
        repository = SqlAlchemyLearningRepository(
            database,
            activity_resolver=evidence_activity,
            reviewer_resolver=lambda _access: None,
            activity_media_resolver=resolve_activity_media_binding_for_learning,
        )
        return LearningCommandBundle(
            repository,
            clock=lambda: now,
            policy_resolver=lambda _access: policy,
        )

    async def scenario() -> None:
        engine = create_async_engine(postgres_harness.schema_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with sessions() as database, database.begin():
                watch = await database.run_sync(
                    lambda sync: commands(sync, NOW).playback.start_session(
                        **scope,
                        expected_revision=0,
                        idempotency_key="continuity-watch-start",
                    )
                )
                original = await _descriptor(database, seed, NOW, delivery_ttl=test_delivery_ttl)
                assert original.delivery is not None
                original_claims = _claims(original.delivery.progressive_url, NOW)
            assert watch.session_token is not None
            assert watch.expires_at == NOW + timedelta(seconds=60)
            watch_scope = {
                **scope,
                "session_id": watch.id,
                "session_token": watch.session_token,
            }

            def evidence_state(
                sync: Session, now: datetime
            ) -> tuple[PlaybackSessionSnapshot, tuple[WatchIntervalSnapshot, ...], VideoCoverage]:
                bundle = commands(sync, now)
                snapshot = bundle.store.get_playback_session(watch.id)
                assert snapshot is not None
                return (
                    snapshot,
                    bundle.store.intervals_for_session(watch.id),
                    bundle.playback.coverage_for_session(**watch_scope),
                )

            for sequence, start, end in ((1, 0, 3), (2, 3, 7)):
                heartbeat_time = NOW + timedelta(seconds=end)
                async with sessions() as database, database.begin():
                    await database.run_sync(
                        lambda sync, sequence=sequence, start=start, end=end, now=heartbeat_time: (
                            commands(sync, now).playback.record_event(
                                **watch_scope,
                                event_id=f"continuity-watch-{sequence}",
                                sequence=sequence,
                                start_seconds=start,
                                end_seconds=end,
                                kind="watch",
                                idempotency_key=f"continuity-heartbeat-{sequence}",
                            )
                        )
                    )
            async with sessions() as database, database.begin():
                before = await database.run_sync(
                    lambda sync: evidence_state(sync, NOW + timedelta(seconds=7))
                )
            before_session, before_intervals, before_coverage = before
            assert before_session.id == watch.id
            assert before_session.last_sequence == before_session.revision == 2
            assert before_session.last_position_seconds == 7
            assert before_session.expires_at == watch.expires_at
            assert before_session.policy_version == policy.version
            assert len(before_intervals) == 2
            assert before_coverage.unique_seconds == 7

            renewal_time = NOW + timedelta(seconds=8)
            async with sessions() as database, database.begin():
                renewed = await _descriptor(
                    database, seed, renewal_time, delivery_ttl=test_delivery_ttl
                )
                assert renewed.delivery is not None
                renewed_claims = _claims(renewed.delivery.progressive_url, renewal_time)
            assert renewed_claims["delivery_grant_id"] != original_claims["delivery_grant_id"]
            assert renewed_claims["iat"] == int(renewal_time.timestamp())
            assert renewed_claims["exp"] - renewed_claims["iat"] == 10
            for name in STABLE_SCOPE_FIELDS:
                assert renewed_claims[name] == original_claims[name]

            async with sessions() as database, database.begin():
                after = await database.run_sync(lambda sync: evidence_state(sync, renewal_time))
            assert after == before

            next_heartbeat_time = NOW + timedelta(seconds=9)
            async with sessions() as database, database.begin():
                interval = await database.run_sync(
                    lambda sync: commands(sync, next_heartbeat_time).playback.record_event(
                        **watch_scope,
                        event_id="continuity-watch-3",
                        sequence=3,
                        start_seconds=7,
                        end_seconds=9,
                        kind="watch",
                        idempotency_key="continuity-heartbeat-3",
                    )
                )
            assert interval.playback_session_id == watch.id

            async with sessions() as database, database.begin():
                final_session, final_intervals, final_coverage = await database.run_sync(
                    lambda sync: evidence_state(sync, next_heartbeat_time)
                )
                assert final_session.id == watch.id
                assert final_session.session_token_hash == watch.session_token_hash
                assert final_session.expires_at == watch.expires_at
                assert final_session.last_sequence == final_session.revision == 3
                assert final_session.last_position_seconds == 9
                assert final_intervals[:2] == before_intervals
                assert len(final_intervals) == 3
                assert final_coverage.unique_seconds == 9
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(PlaybackSession)
                        .where(PlaybackSession.enrollment_id == seed.enrollment_id)
                    )
                    == 1
                )
                grants = (
                    await database.scalars(
                        select(MediaPlaybackGrant).where(
                            MediaPlaybackGrant.tenant_id == seed.actor.tenant_id,
                            MediaPlaybackGrant.actor_person_id == seed.actor.person_id,
                        )
                    )
                ).all()
                assert {str(grant.id) for grant in grants} == {
                    original_claims["delivery_grant_id"],
                    renewed_claims["delivery_grant_id"],
                }
        finally:
            await engine.dispose()

    _run_async(scenario())
