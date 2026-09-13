"""PostgreSQL proof for the reviewed Free Course publish/promote/deliver path.

The shared harness creates and drops a disposable migrated schema.  The test
uses the real async applications and binding ledger, while its private object
store is the explicit in-memory adapter used only for deterministic test
bytes; no deployed provider or runtime is contacted.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import sys
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.authorization.application import CapabilityApplication
from ac_platform.authorization.policy import CapabilityScope
from ac_platform.catalog import cli as catalog_cli
from ac_platform.catalog.free_course_media import FreeCourseMediaPromotionApplication
from ac_platform.catalog.free_course_publication import (
    AUTHORITY_CLOSERS_FREE_COURSE_SLUG,
    FreeCoursePublicationApplication,
)
from ac_platform.catalog.models import (
    CatalogScope,
    Module,
    Program,
    ProgramVersion,
)
from ac_platform.catalog.services import CatalogService, SqlAlchemyCatalogStore
from ac_platform.enrollment.models import Enrollment, EnrollmentEligibilityFact
from ac_platform.enrollment.services import AsyncEnrollmentApplication, FreeEnrollmentCommand
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.learning.catalog_activity import resolve_catalog_activity
from ac_platform.learning.models import ActivityProgress
from ac_platform.learning.services import SqlAlchemyLearningRepository
from ac_platform.media.database_delivery_authorizer import DatabaseMediaDeliveryAuthorizer
from ac_platform.media.delivery import PrivateMediaDeliveryHandler
from ac_platform.media.models import (
    ActivityMediaBinding,
    MediaAsset,
    MediaLifecycle,
    MediaPurpose,
    MediaRendition,
    MediaUploadIntent,
    MediaVersion,
    StudioVideoUpload,
)
from ac_platform.media.policy import MediaCorsPolicy, SignedMediaDeliveryPort
from ac_platform.media.service import MediaService
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import InMemoryPrivateObjectStorage
from ac_platform.tenancy.models import Membership, Tenant
from tests.integration.test_media_delivery_renewal_postgresql import (
    postgres_harness,  # noqa: F401 - shared disposable PostgreSQL schema
)

# Keep the fixture's reference time close to the wall clock used by the
# authorization and media-delivery boundaries.  Individual expiry fixtures
# continue to derive from this value, so their expired/current distinction is
# preserved while long-lived CI runs do not age the named sessions out before
# the proof reaches them.
NOW = datetime.now(UTC)
TEST_SESSION_PEPPER = b"local-session-token-pepper-change-before-production"


def _refresh_fixture_clock() -> None:
    """Refresh the disposable fixture clock immediately before each proof."""

    global NOW
    NOW = datetime.now(UTC)


def _run(coroutine):
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


async def _exercise(schema_url) -> None:
    _refresh_fixture_clock()
    engine = create_async_engine(schema_url, hide_parameters=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        operations_id, public_id = uuid4(), uuid4()
        manager_id, learner_id = uuid4(), uuid4()
        manager_session_id, learner_session_id = uuid4(), uuid4()
        source_asset_id, source_version_id = uuid4(), uuid4()
        source_slug = f"postgres-free-course-{uuid4().hex}"
        async with sessions() as database, database.begin():
            database.add_all(
                [
                    Tenant(id=operations_id, slug=f"ops-{operations_id.hex}", name="Operations"),
                    Tenant(id=public_id, slug=f"public-{public_id.hex}", name="Public learners"),
                    Person(
                        id=manager_id,
                        email=f"manager-{manager_id.hex}@example.test",
                        email_verified_at=NOW,
                    ),
                    Person(
                        id=learner_id,
                        email=f"learner-{learner_id.hex}@example.test",
                        email_verified_at=NOW,
                    ),
                ]
            )
            await database.flush()
            database.add_all(
                [
                    Membership(tenant_id=operations_id, person_id=manager_id, role="owner"),
                    Membership(tenant_id=public_id, person_id=manager_id, role="learner"),
                    Membership(tenant_id=public_id, person_id=learner_id, role="learner"),
                ]
            )
            await database.flush()
            database.add_all(
                [
                    IdentitySession(
                        id=manager_session_id,
                        person_id=manager_id,
                        selected_tenant_id=operations_id,
                        token_hash=hashlib.sha256(manager_session_id.bytes).digest(),
                        created_at=NOW - timedelta(minutes=1),
                        expires_at=NOW + timedelta(hours=1),
                    ),
                    IdentitySession(
                        id=learner_session_id,
                        person_id=learner_id,
                        selected_tenant_id=public_id,
                        token_hash=hashlib.sha256(learner_session_id.bytes).digest(),
                        created_at=NOW - timedelta(minutes=1),
                        expires_at=NOW + timedelta(hours=1),
                    ),
                ]
            )
            await database.flush()

            def create_source(sync):
                catalog = CatalogService(SqlAlchemyCatalogStore(sync), clock=lambda: NOW)
                source = catalog.create_program(
                    tenant_id=operations_id,
                    scope=CatalogScope.TENANT,
                    slug=source_slug,
                    title="PostgreSQL reviewed Free Course",
                    program_id=uuid4(),
                    now=NOW,
                )
                version = catalog.create_version(
                    source.id,
                    tenant_id=operations_id,
                    version_number=1,
                    now=NOW,
                )
                module = catalog.add_module(
                    version.id,
                    tenant_id=operations_id,
                    position=1,
                    title="Module 1",
                )
                catalog.add_activity(
                    module.id,
                    tenant_id=operations_id,
                    position=1,
                    kind="VIDEO",
                    title="Reviewed test video",
                    prompt="Watch the licensed test lesson.",
                    is_required=True,
                )
                snapshot = catalog.get_version(version.id, tenant_id=operations_id)
                assert snapshot is not None
                row = sync.get(ProgramVersion, version.id)
                assert row is not None
                row.content_digest = catalog._canonical_content_digest(snapshot)  # noqa: SLF001
                row.content_source_ref = "controlled:postgres-free-course-test"
                row.content_reviewed_by = f"person:{manager_id}"
                row.content_reviewed_at = NOW
                row.release_id = "b" * 40
                row.content_seed_kind = "reviewed"
                sync.flush()
                catalog.publish_version(version.id, tenant_id=operations_id, now=NOW)
                return source.id

            source_program_id = await database.run_sync(create_source)
            actor = ActorContext(
                manager_id,
                manager_session_id,
                operations_id,
                permissions=frozenset({"catalog_read", "catalog_write", "catalog_publish"}),
            )
            signer = MediaSigner(b"postgres-free-course-test-signing-key-32bytes")
            storage = InMemoryPrivateObjectStorage(signer)
            source_prefix = (
                f"tenants/{operations_id}/media/video/{source_asset_id}/{source_version_id}/"
            )
            source_body = b"postgres reviewed source bytes"
            original = storage.put(
                object_key=source_prefix + "original",
                body=source_body,
                content_type="video/mp4",
            )
            rendition = storage.put(
                object_key=source_prefix + "renditions/progressive.mp4",
                body=source_body,
                content_type="video/mp4",
            )
            database.add(
                MediaAsset(
                    id=source_asset_id,
                    tenant_id=operations_id,
                    owner_person_id=manager_id,
                    purpose=MediaPurpose.VIDEO.value,
                    state=MediaLifecycle.READY.value,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            database.add(
                MediaVersion(
                    id=source_version_id,
                    tenant_id=operations_id,
                    asset_id=source_asset_id,
                    version_number=1,
                    purpose=MediaPurpose.VIDEO.value,
                    state=MediaLifecycle.READY.value,
                    content_type="video/mp4",
                    declared_bytes=len(source_body),
                    actual_bytes=original.content_length,
                    checksum_sha256=original.checksum_sha256,
                    object_key=original.object_key,
                    storage_version_id=original.storage_version_id,
                    duration_seconds=12.0,
                    width=3840,
                    height=2160,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await database.flush()
            source_asset = await database.get(MediaAsset, source_asset_id)
            assert source_asset is not None
            source_asset.current_version_id = source_version_id
            database.add(
                MediaUploadIntent(
                    id=uuid4(),
                    tenant_id=operations_id,
                    actor_person_id=manager_id,
                    asset_id=source_asset_id,
                    version_id=source_version_id,
                    object_key=original.object_key,
                    filename="approved-test-video.mp4",
                    content_type="video/mp4",
                    declared_bytes=original.content_length,
                    checksum_sha256=original.checksum_sha256,
                    expires_at=NOW - timedelta(minutes=1),
                    max_bytes=original.content_length,
                    state=MediaLifecycle.READY.value,
                    idempotency_key="postgres-free-course-source-upload",
                    request_fingerprint="a" * 64,
                    completion_fingerprint="b" * 64,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await database.flush()
            source_upload = (
                await database.execute(
                    select(MediaUploadIntent).where(
                        MediaUploadIntent.asset_id == source_asset_id,
                        MediaUploadIntent.version_id == source_version_id,
                    )
                )
            ).scalar_one()
            database.add(
                StudioVideoUpload(
                    upload_id=source_upload.id,
                    tenant_id=operations_id,
                    program_id=source_program_id,
                    created_at=NOW,
                )
            )
            database.add(
                MediaRendition(
                    id=uuid4(),
                    tenant_id=operations_id,
                    asset_id=source_asset_id,
                    version_id=source_version_id,
                    protocol="progressive",
                    content_type="video/mp4",
                    object_key=rendition.object_key,
                    width=3840,
                    height=2160,
                )
            )
            await database.flush()

            async def test_platform_projection(*_args, **_kwargs):
                return frozenset({"platform_catalog_write", "platform_catalog_publish"})

            # The harness is module-scoped; reserve the canonical slug and
            # durable capability history for the independent legacy adoption
            # fixture below while exercising the same publication path here.
            with (
                patch(
                    "ac_platform.catalog.free_course_publication.AUTHORITY_CLOSERS_FREE_COURSE_SLUG",
                    f"postgres-free-course-publication-{uuid4().hex}",
                ),
                patch(
                    "ac_platform.authorization.platform.platform_projection",
                    new=test_platform_projection,
                ),
            ):
                publication = await FreeCoursePublicationApplication(
                    database,
                    operations_tenant_id=operations_id,
                    public_tenant_id=public_id,
                    clock=lambda: NOW,
                ).apply(
                    actor=actor,
                    source_program_id=source_program_id,
                    command_id=uuid4(),
                    reason="PostgreSQL reviewed Free Course publication",
                )
            assert publication.video_activity_id

            port = SignedMediaDeliveryPort(
                signer=signer,
                delivery_origin="https://learner.test",
                playback_ttl=timedelta(minutes=15),
            )
            service = MediaService(
                storage=storage,
                signer=signer,
                webhook_secret=b"postgres-free-course-webhook-secret-32",
                delivery_port=port,
                delivery_activity_resolver=resolve_catalog_activity,
            )
            service._now = lambda: NOW
            with patch(
                "ac_platform.catalog.free_course_media.platform_projection",
                new=test_platform_projection,
            ):
                promoted = await FreeCourseMediaPromotionApplication(
                    database,
                    service=service,
                    operations_tenant_id=operations_id,
                    public_tenant_id=public_id,
                    clock=lambda: NOW,
                ).apply(
                    actor=actor,
                    publication_command_id=publication.command_id,
                    command_id=uuid4(),
                    activity_id=publication.video_activity_id,
                    source_asset_id=source_asset_id,
                    source_version_id=source_version_id,
                    media_owner_person_id=manager_id,
                    approval_reference="PG-FREE-COURSE-HTTP-TEST",
                )
            binding = await database.get(ActivityMediaBinding, promoted.binding_id)
            assert binding is not None and binding.state == "approved"

            eligibility = EnrollmentEligibilityFact(
                id=uuid4(),
                tenant_id=public_id,
                person_id=learner_id,
                program_version_id=publication.program_version_id,
                program_id=publication.program_id,
                program_scope=CatalogScope.GLOBAL.value,
                program_tenant_id=None,
                program_owner_key=UUID(int=0),
                age_gate_passed=True,
                eligibility_passed=True,
                prerequisites_satisfied=True,
                policy_version="postgres-free-course-http-test",
                evidence={"test_only": True},
                evaluated_at=NOW,
            )
            database.add(eligibility)
            await database.flush()
            learner_actor = ActorContext(learner_id, learner_session_id, public_id)
            enrollment = await AsyncEnrollmentApplication(database).enroll_free(
                FreeEnrollmentCommand(
                    actor_person_id=learner_id,
                    subject_person_id=learner_id,
                    tenant_id=public_id,
                    program_version_id=publication.program_version_id,
                    idempotency_key=f"postgres-free-course-{uuid4().hex}",
                ),
                actor=learner_actor,
            )
            access = await database.run_sync(
                lambda sync: SqlAlchemyLearningRepository(
                    sync,
                    activity_resolver=resolve_catalog_activity,
                    reviewer_resolver=lambda _access: None,
                    activity_media_resolver=service.resolve_activity_media_binding_for_learning,
                ).resolve_access(
                    actor=learner_actor,
                    tenant_id=public_id,
                    enrollment_id=enrollment.enrollment_id,
                    program_version_id=publication.program_version_id,
                    activity_id=publication.video_activity_id,
                )
            )
            descriptor = await service.resolve_activity_media_descriptor_for_learner(
                database, learner_actor, access
            )
            assert descriptor.delivery is not None and descriptor.delivery.progressive_url
            token = parse_qs(urlsplit(descriptor.delivery.progressive_url).query)["token"][0]
            target_key = (
                f"tenants/{public_id}/media/video/{promoted.asset_id}/{promoted.version_id}/"
                "renditions/progressive.mp4"
            )

            def serve(sync):
                handler = PrivateMediaDeliveryHandler(
                    storage=storage,
                    signer=signer,
                    delivery_port=port,
                    cors_policy=MediaCorsPolicy(("https://learner.test",)),
                    authorizer=DatabaseMediaDeliveryAuthorizer(
                        sync,
                        learner_actor,
                        signer=signer,
                        activity_resolver=resolve_catalog_activity,
                        clock=lambda: NOW,
                    ),
                )
                response = handler.serve(
                    token=unquote(token),
                    token_type="playback",  # noqa: S106 - bounded token kind, not a secret
                    object_key=target_key,
                    origin="https://learner.test",
                    now=NOW,
                )
                return response.status_code, b"".join(response.body or ())

            status_code, body = await database.run_sync(serve)
            assert status_code == 200
            assert body == source_body

    finally:
        await engine.dispose()


def test_postgresql_free_course_publish_promote_and_http_delivery(postgres_harness) -> None:  # noqa: F811
    _run(_exercise(postgres_harness.schema_url))


async def _exercise_cli_actor(schema_url) -> None:
    """Exercise adoption against the actual legacy staging row shape."""

    _refresh_fixture_clock()
    engine = create_async_engine(schema_url, hide_parameters=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    token = "A" * 43
    try:
        operations_id, public_id = uuid4(), uuid4()
        manager_id, learner_id, session_id = uuid4(), uuid4(), uuid4()
        source_program_id, source_version_id = uuid4(), uuid4()
        target_program_id, target_version_id, target_video_id = uuid4(), uuid4(), uuid4()
        source_upload_id, source_asset_id, source_media_version_id = uuid4(), uuid4(), uuid4()
        target_asset_id, target_media_version_id = uuid4(), uuid4()
        enrollment_id, progress_id, binding_id = uuid4(), uuid4(), uuid4()
        legacy_reviewer_id = uuid4()

        async with sessions() as database, database.begin():
            database.add_all(
                [
                    Tenant(
                        id=operations_id,
                        slug=f"ops-legacy-adoption-{operations_id.hex}",
                        name="Operations",
                    ),
                    Tenant(
                        id=public_id,
                        slug=f"public-legacy-adoption-{public_id.hex}",
                        name="Public learners",
                    ),
                    Person(
                        id=manager_id,
                        email=f"coach-legacy-adoption-{manager_id.hex}@example.test",
                        email_verified_at=NOW,
                    ),
                    Person(
                        id=learner_id,
                        email=f"learner-legacy-adoption-{learner_id.hex}@example.test",
                        email_verified_at=NOW,
                    ),
                ]
            )
            await database.flush()
            database.add_all(
                [
                    Membership(tenant_id=operations_id, person_id=manager_id, role="owner"),
                    Membership(tenant_id=public_id, person_id=manager_id, role="learner"),
                    Membership(tenant_id=public_id, person_id=learner_id, role="learner"),
                ]
            )
            await database.flush()
            database.add(
                IdentitySession(
                    id=session_id,
                    person_id=manager_id,
                    selected_tenant_id=operations_id,
                    token_hash=hmac.new(
                        TEST_SESSION_PEPPER, token.encode("ascii"), hashlib.sha256
                    ).digest(),
                    created_at=NOW - timedelta(minutes=1),
                    expires_at=NOW + timedelta(hours=1),
                )
            )
            await database.flush()

            def create_catalog(sync):
                catalog = CatalogService(SqlAlchemyCatalogStore(sync), clock=lambda: NOW)
                source = catalog.create_program(
                    tenant_id=operations_id,
                    scope=CatalogScope.TENANT,
                    slug=f"coach-draft-{source_program_id.hex}",
                    title="Coach draft: Module 1 test media",
                    program_id=source_program_id,
                    now=NOW,
                )
                source_version = catalog.create_version(
                    source.id,
                    tenant_id=operations_id,
                    version_number=1,
                    version_id=source_version_id,
                    now=NOW,
                )
                source_module = catalog.add_module(
                    source_version.id,
                    tenant_id=operations_id,
                    position=1,
                    title="Module 1",
                )
                catalog.add_activity(
                    source_module.id,
                    tenant_id=operations_id,
                    position=1,
                    kind="VIDEO",
                    title="Watch the licensed test film",
                    prompt="Watch the explicitly labelled test lesson.",
                    is_required=True,
                )

                target = catalog.create_program(
                    tenant_id=None,
                    scope=CatalogScope.GLOBAL,
                    slug=AUTHORITY_CLOSERS_FREE_COURSE_SLUG,
                    title="Existing staging public course",
                    program_id=target_program_id,
                    now=NOW,
                )
                target_version = catalog.create_version(
                    target.id,
                    tenant_id=None,
                    version_number=7,
                    version_id=target_version_id,
                    content_source_ref="staging:legacy-course-export",
                    content_reviewed_by=f"person:{legacy_reviewer_id}",
                    content_reviewed_at=NOW - timedelta(days=7),
                    release_id="d" * 40,
                    content_seed_kind="reviewed",
                    now=NOW,
                )
                target_modules = []
                for position in range(1, 5):
                    module = catalog.add_module(
                        target_version.id,
                        tenant_id=None,
                        position=position,
                        title=f"Legacy module {position}",
                    )
                    target_modules.append(module)
                    if position > 1:
                        catalog.add_module_prerequisite(
                            module.id,
                            target_modules[-2].id,
                            tenant_id=None,
                        )
                    catalog.add_activity(
                        module.id,
                        tenant_id=None,
                        position=1,
                        kind="VIDEO" if position == 1 else "REFLECTION",
                        title="Legacy video" if position == 1 else f"Legacy reflection {position}",
                        prompt=(
                            "Existing approved test film"
                            if position == 1
                            else f"Legacy reflection prompt {position}"
                        ),
                        is_required=True,
                        activity_id=target_video_id if position == 1 else uuid4(),
                    )
                snapshot = catalog.get_version(target_version.id, tenant_id=None)
                assert snapshot is not None
                row = sync.get(ProgramVersion, target_version.id)
                assert row is not None
                row.content_digest = catalog._canonical_content_digest(snapshot)  # noqa: SLF001
                sync.flush()
                catalog.publish_version(target_version.id, tenant_id=None, now=NOW)
                return tuple(target_modules)

            target_modules = await database.run_sync(create_catalog)
            source_prefix = (
                f"tenants/{operations_id}/media/video/{source_asset_id}/{source_media_version_id}/"
            )
            database.add_all(
                [
                    MediaAsset(
                        id=source_asset_id,
                        tenant_id=operations_id,
                        owner_person_id=manager_id,
                        purpose=MediaPurpose.VIDEO.value,
                        state=MediaLifecycle.READY.value,
                        created_at=NOW,
                        updated_at=NOW,
                    ),
                    MediaVersion(
                        id=source_media_version_id,
                        tenant_id=operations_id,
                        asset_id=source_asset_id,
                        version_number=1,
                        purpose=MediaPurpose.VIDEO.value,
                        state=MediaLifecycle.READY.value,
                        content_type="video/mp4",
                        declared_bytes=633_000_000,
                        actual_bytes=633_000_000,
                        checksum_sha256="5" * 64,
                        object_key=source_prefix + "original",
                        storage_version_id="source-ready-v1",
                        duration_seconds=12.0,
                        width=3840,
                        height=2160,
                        created_at=NOW,
                        updated_at=NOW,
                    ),
                ]
            )
            await database.flush()
            source_asset = await database.get(MediaAsset, source_asset_id)
            assert source_asset is not None
            source_asset.current_version_id = source_media_version_id
            database.add(
                MediaUploadIntent(
                    id=source_upload_id,
                    tenant_id=operations_id,
                    actor_person_id=manager_id,
                    asset_id=source_asset_id,
                    version_id=source_media_version_id,
                    object_key=source_prefix + "original",
                    filename="big-buck-bunny-4k-test.mp4",
                    content_type="video/mp4",
                    declared_bytes=633_000_000,
                    checksum_sha256="5" * 64,
                    expires_at=NOW - timedelta(minutes=1),
                    max_bytes=2_000_000_000,
                    state=MediaLifecycle.READY.value,
                    idempotency_key="legacy-adoption-source-upload",
                    request_fingerprint="2" * 64,
                    completion_fingerprint="6" * 64,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            database.add(
                StudioVideoUpload(
                    upload_id=source_upload_id,
                    tenant_id=operations_id,
                    program_id=source_program_id,
                    created_at=NOW,
                )
            )
            target_prefix = (
                f"tenants/{public_id}/media/video/{target_asset_id}/{target_media_version_id}/"
            )
            database.add_all(
                [
                    MediaAsset(
                        id=target_asset_id,
                        tenant_id=public_id,
                        owner_person_id=manager_id,
                        purpose=MediaPurpose.VIDEO.value,
                        state=MediaLifecycle.READY.value,
                        created_at=NOW,
                        updated_at=NOW,
                    ),
                    MediaVersion(
                        id=target_media_version_id,
                        tenant_id=public_id,
                        asset_id=target_asset_id,
                        version_number=1,
                        purpose=MediaPurpose.VIDEO.value,
                        state=MediaLifecycle.READY.value,
                        content_type="video/mp4",
                        declared_bytes=12,
                        actual_bytes=12,
                        checksum_sha256="3" * 64,
                        object_key=target_prefix + "original",
                        storage_version_id="legacy-target-v1",
                        duration_seconds=12.0,
                        width=3840,
                        height=2160,
                        created_at=NOW,
                        updated_at=NOW,
                    ),
                ]
            )
            await database.flush()
            target_asset = await database.get(MediaAsset, target_asset_id)
            assert target_asset is not None
            target_asset.current_version_id = target_media_version_id
            database.add(
                MediaRendition(
                    id=uuid4(),
                    tenant_id=public_id,
                    asset_id=target_asset_id,
                    version_id=target_media_version_id,
                    protocol="progressive",
                    content_type="video/mp4",
                    object_key=target_prefix + "renditions/progressive.mp4",
                    width=3840,
                    height=2160,
                )
            )
            database.add(
                ActivityMediaBinding(
                    id=binding_id,
                    tenant_id=public_id,
                    activity_id=target_video_id,
                    module_id=target_modules[0].id,
                    program_version_id=target_version_id,
                    program_id=target_program_id,
                    program_scope=CatalogScope.GLOBAL.value,
                    program_owner_key=UUID(int=0),
                    activity_version=f"activity:{target_video_id}",
                    asset_id=target_asset_id,
                    version_id=target_media_version_id,
                    state="approved",
                    approval_reference="legacy-staging-binding",
                    approved_by_person_id=manager_id,
                    approved_at=NOW,
                    idempotency_key="legacy-staging-binding",
                    request_fingerprint="4" * 64,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            database.add(
                Enrollment(
                    id=enrollment_id,
                    tenant_id=public_id,
                    person_id=learner_id,
                    program_version_id=target_version_id,
                    program_id=target_program_id,
                    program_scope=CatalogScope.GLOBAL.value,
                    program_tenant_id=None,
                    program_owner_key=UUID(int=0),
                    source="free_self",
                    status="active",
                    enrolled_at=NOW,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            database.add(
                ActivityProgress(
                    id=progress_id,
                    tenant_id=public_id,
                    person_id=learner_id,
                    enrollment_id=enrollment_id,
                    program_version_id=target_version_id,
                    program_id=target_program_id,
                    program_scope=CatalogScope.GLOBAL.value,
                    program_owner_key=UUID(int=0),
                    module_id=target_modules[0].id,
                    activity_id=target_video_id,
                    state="in_progress",
                    activity_version=f"activity:{target_video_id}",
                    policy_version="legacy-progress-v1",
                    revision=4,
                    started_at=NOW - timedelta(hours=1),
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await database.flush()

            target_program = await database.get(Program, target_program_id)
            target_version = await database.get(ProgramVersion, target_version_id)
            current_binding = await database.get(ActivityMediaBinding, binding_id)
            current_enrollment = await database.get(Enrollment, enrollment_id)
            current_progress = await database.get(ActivityProgress, progress_id)
            source_admission = await database.get(StudioVideoUpload, source_upload_id)
            assert (
                target_program is not None
                and target_version is not None
                and current_binding is not None
                and current_enrollment is not None
                and current_progress is not None
                and source_admission is not None
            )
            before_catalog = {
                "program_title": target_program.title,
                "version_digest": target_version.content_digest,
                "version_source_ref": target_version.content_source_ref,
                "version_reviewed_by": target_version.content_reviewed_by,
                "version_reviewed_at": target_version.content_reviewed_at,
                "version_release_id": target_version.release_id,
                "version_seed_kind": target_version.content_seed_kind,
                "module_ids": tuple(module.id for module in target_modules),
                "binding": (
                    current_binding.state,
                    current_binding.asset_id,
                    current_binding.version_id,
                    current_binding.approval_reference,
                ),
                "enrollment": (current_enrollment.status, current_enrollment.program_version_id),
                "progress": (current_progress.state, current_progress.revision),
                "source_admission": (source_admission.program_id, source_admission.upload_id),
            }

            actor = ActorContext(
                manager_id,
                session_id,
                operations_id,
                permissions=frozenset({"catalog_read", "catalog_write", "catalog_publish"}),
            )
            capability = CapabilityApplication(database, operations_tenant_id=operations_id)
            await capability.bootstrap_first_manager(
                person_id=manager_id,
                command_id=uuid4(),
                reason="PostgreSQL legacy adoption test bootstrap",
            )
            for permission in ("platform_catalog_write", "platform_catalog_publish"):
                await capability.grant(
                    actor,
                    command_id=uuid4(),
                    subject_person_id=manager_id,
                    permission=permission,
                    scope=CapabilityScope("platform"),
                    reason="PostgreSQL legacy adoption test authority",
                )

        args = catalog_cli._parser().parse_args(  # noqa: SLF001 - actual CLI entry proof
            [
                "adopt-existing",
                "--environment",
                "test",
                "--source-program-id",
                str(source_program_id),
                "--program-id",
                str(target_program_id),
                "--program-version-id",
                str(target_version_id),
                "--video-activity-id",
                str(target_video_id),
                "--public-tenant-id",
                str(public_id),
                "--command-id",
                str(uuid4()),
                "--reason",
                "Adopt the reviewed legacy public course without changing progress",
            ]
        )
        environment = {
            "AC_DATABASE_URL": schema_url.render_as_string(hide_password=False),
            "AC_ENVIRONMENT": "test",
            "AC_OPERATIONS_TENANT_ID": str(operations_id),
        }
        with (
            patch.dict(os.environ, environment, clear=False),
            patch.object(catalog_cli, "_read_session_token", lambda: token),
        ):
            result = await catalog_cli._execute(args)  # noqa: SLF001 - actual CLI entry proof
        assert result["status"] == "adopted"
        assert UUID(str(result["video_activity_id"])) == target_video_id

        async with sessions() as database, database.begin():
            target_program = await database.get(Program, target_program_id)
            target_version = await database.get(ProgramVersion, target_version_id)
            current_binding = await database.get(ActivityMediaBinding, binding_id)
            current_enrollment = await database.get(Enrollment, enrollment_id)
            current_progress = await database.get(ActivityProgress, progress_id)
            source_admission = await database.get(StudioVideoUpload, source_upload_id)
            assert (
                target_program is not None
                and target_version is not None
                and current_binding is not None
                and current_enrollment is not None
                and current_progress is not None
                and source_admission is not None
            )
            assert target_program.title == before_catalog["program_title"]
            assert (
                target_version.content_digest,
                target_version.content_source_ref,
                target_version.content_reviewed_by,
                target_version.content_reviewed_at,
                target_version.release_id,
                target_version.content_seed_kind,
            ) == (
                before_catalog["version_digest"],
                before_catalog["version_source_ref"],
                before_catalog["version_reviewed_by"],
                before_catalog["version_reviewed_at"],
                before_catalog["version_release_id"],
                before_catalog["version_seed_kind"],
            )
            assert (
                current_binding.state,
                current_binding.asset_id,
                current_binding.version_id,
                current_binding.approval_reference,
            ) == before_catalog["binding"]
            assert (
                current_enrollment.status,
                current_enrollment.program_version_id,
            ) == before_catalog["enrollment"]
            assert (current_progress.state, current_progress.revision) == before_catalog["progress"]
            assert (source_admission.program_id, source_admission.upload_id) == before_catalog[
                "source_admission"
            ]
            modules = tuple(
                await database.scalars(
                    select(Module)
                    .where(Module.program_version_id == target_version_id)
                    .order_by(Module.position)
                )
            )
            assert tuple(module.id for module in modules) == before_catalog["module_ids"]
            source_version = await database.get(ProgramVersion, source_version_id)
            assert source_version is not None
            assert source_version.status == "draft"
    finally:
        await engine.dispose()


def test_postgresql_free_course_cli_resolves_role_permissions(postgres_harness) -> None:  # noqa: F811
    _run(_exercise_cli_actor(postgres_harness.schema_url))
