"""PostgreSQL proof for the reviewed Free Course publish/promote/deliver path.

The shared harness creates and drops a disposable migrated schema.  The test
uses the real async applications and binding ledger, while its private object
store is the explicit in-memory adapter used only for deterministic test
bytes; no deployed provider or runtime is contacted.
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.authorization.application import CapabilityApplication
from ac_platform.authorization.policy import CapabilityScope
from ac_platform.catalog.free_course_media import FreeCourseMediaPromotionApplication
from ac_platform.catalog.free_course_publication import FreeCoursePublicationApplication
from ac_platform.catalog.models import CatalogScope, ProgramVersion
from ac_platform.catalog.services import CatalogService, SqlAlchemyCatalogStore
from ac_platform.enrollment.models import EnrollmentEligibilityFact
from ac_platform.enrollment.services import AsyncEnrollmentApplication, FreeEnrollmentCommand
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.learning.catalog_activity import resolve_catalog_activity
from ac_platform.learning.services import SqlAlchemyLearningRepository
from ac_platform.media.database_delivery_authorizer import DatabaseMediaDeliveryAuthorizer
from ac_platform.media.delivery import PrivateMediaDeliveryHandler
from ac_platform.media.models import (
    ActivityMediaBinding,
    MediaAsset,
    MediaLifecycle,
    MediaPurpose,
    MediaRendition,
    MediaVersion,
)
from ac_platform.media.policy import MediaCorsPolicy, SignedMediaDeliveryPort
from ac_platform.media.service import MediaService
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import InMemoryPrivateObjectStorage
from ac_platform.tenancy.models import Membership, Tenant
from tests.integration.test_media_delivery_renewal_postgresql import (
    postgres_harness,  # noqa: F401 - shared disposable PostgreSQL schema
)

NOW = datetime(2026, 9, 13, 12, tzinfo=UTC)


def _run(coroutine):
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


async def _exercise(schema_url) -> None:
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
                    Membership(tenant_id=operations_id, person_id=manager_id, role="owner"),
                    Membership(tenant_id=public_id, person_id=manager_id, role="learner"),
                    Membership(tenant_id=public_id, person_id=learner_id, role="learner"),
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
            capability = CapabilityApplication(database, operations_tenant_id=operations_id)
            await capability.bootstrap_first_manager(
                person_id=manager_id,
                command_id=uuid4(),
                reason="PostgreSQL Free Course test bootstrap",
            )
            for permission in ("platform_catalog_write", "platform_catalog_publish"):
                await capability.grant(
                    actor,
                    command_id=uuid4(),
                    subject_person_id=manager_id,
                    permission=permission,
                    scope=CapabilityScope("platform"),
                    reason="PostgreSQL Free Course test authority",
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
                    ),
                )
                response = handler.serve(
                    token=unquote(token),
                    token_type="playback",  # noqa: S106 - bounded token kind, not a secret
                    object_key=target_key,
                    origin="https://learner.test",
                )
                return response.status_code, b"".join(response.body or ())

            status_code, body = await database.run_sync(serve)
            assert status_code == 200
            assert body == source_body

    finally:
        await engine.dispose()


def test_postgresql_free_course_publish_promote_and_http_delivery(postgres_harness) -> None:  # noqa: F811
    _run(_exercise(postgres_harness.schema_url))
