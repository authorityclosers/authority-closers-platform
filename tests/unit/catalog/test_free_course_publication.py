"""Relational checks for the bounded Coach-to-global Free Course command."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from ac_platform.authorization.policy import CapabilityScope
from ac_platform.catalog.content import (
    CanonicalActivityContent,
    CanonicalModuleContent,
    canonical_catalog_content_digest,
)
from ac_platform.catalog.free_course_media import FreeCourseMediaPromotionApplication
from ac_platform.catalog.free_course_publication import (
    AUTHORITY_CLOSERS_FREE_COURSE_SLUG,
    FreeCoursePublicationApplication,
    FreeCoursePublicationConflict,
    FreeCoursePublicationError,
)
from ac_platform.catalog.models import (
    Activity,
    CatalogScope,
    Program,
    ProgramVersion,
    ProgramVersionStatus,
)
from ac_platform.catalog.services import CatalogService, SqlAlchemyCatalogStore
from ac_platform.http.auth import ROLE_PERMISSIONS
from ac_platform.media.models import (
    ActivityMediaBinding,
    MediaAsset,
    MediaLifecycle,
    MediaPurpose,
    MediaRendition,
    MediaVersion,
)
from ac_platform.media.service import MediaService
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import InMemoryPrivateObjectStorage
from tests.unit.authorization.test_capability_application import AwaitableSession, bootstrap
from tests.unit.authorization.test_capability_application import state as state  # noqa: F401

NOW = datetime(2026, 9, 13, 12, tzinfo=UTC)
RELEASE = "a" * 40


class PublicationSession(AwaitableSession):
    @asynccontextmanager
    async def begin_nested(self):
        with self.database.begin_nested():
            yield

    async def run_sync(self, operation):
        return operation(self.database)


async def _grant_publication_capabilities(state) -> None:
    await bootstrap(state)
    for permission in ("platform_catalog_write", "platform_catalog_publish"):
        await state.app.grant(
            state.actor,
            command_id=uuid4(),
            subject_person_id=state.manager,
            permission=permission,
            scope=CapabilityScope("platform"),
            reason="Approved Free Course publication responsibility",
        )


def _source_course(state, *, publish: bool = True):
    service = CatalogService(SqlAlchemyCatalogStore(state.db), clock=lambda: NOW)
    program_id = uuid4()
    program = service.create_program(
        tenant_id=state.operations,
        scope=CatalogScope.TENANT,
        slug=f"course-{program_id.hex}",
        title="Authority Closers Free Course",
        program_id=program_id,
        now=NOW,
    )
    digest = canonical_catalog_content_digest(
        program_slug=program.slug,
        program_title=program.title,
        modules=(
            CanonicalModuleContent(
                position=1,
                title="Module 1",
                prerequisite_positions=(),
                activities=(
                    CanonicalActivityContent(
                        position=1,
                        kind="VIDEO",
                        title="Watch",
                        is_required=True,
                        prompt="Watch the reviewed test lesson.",
                    ),
                    CanonicalActivityContent(
                        position=2,
                        kind="REFLECTION",
                        title="Reflect",
                        is_required=True,
                        prompt="Write one reflection.",
                    ),
                ),
            ),
        ),
    )
    version = service.create_version(
        program.id,
        tenant_id=state.operations,
        version_number=1,
        content_digest=digest if publish else None,
        content_source_ref="controlled:test-source" if publish else None,
        content_reviewed_by=f"person:{state.manager}" if publish else None,
        content_reviewed_at=NOW if publish else None,
        release_id=RELEASE if publish else None,
        content_seed_kind="reviewed" if publish else None,
        now=NOW,
    )
    module = service.add_module(
        version.id,
        tenant_id=state.operations,
        position=1,
        title="Module 1",
    )
    service.add_activity(
        module.id,
        tenant_id=state.operations,
        position=1,
        kind="VIDEO",
        title="Watch",
        prompt="Watch the reviewed test lesson.",
        is_required=True,
    )
    service.add_activity(
        module.id,
        tenant_id=state.operations,
        position=2,
        kind="REFLECTION",
        title="Reflect",
        prompt="Write one reflection.",
        is_required=True,
    )
    if publish:
        service.publish_version(version.id, tenant_id=state.operations, now=NOW)
    return program


async def test_publication_is_idempotent_and_preserves_tenant_source(state) -> None:
    await _grant_publication_capabilities(state)
    source = _source_course(state)
    actor = replace(
        state.actor,
        tenant_id=state.operations,
        permissions=ROLE_PERMISSIONS["owner"],
    )
    command_id = uuid4()
    application = FreeCoursePublicationApplication(
        PublicationSession(state.db),
        operations_tenant_id=state.operations,
        public_tenant_id=state.other,
        clock=lambda: NOW,
    )

    result = await application.apply(
        actor=actor,
        source_program_id=source.id,
        command_id=command_id,
        reason="Approved initial public Free Course publication",
    )
    replay = await application.apply(
        actor=actor,
        source_program_id=source.id,
        command_id=command_id,
        reason="Approved initial public Free Course publication",
    )

    assert result.status == "published"
    assert replay.status == "replayed"
    assert replay.program_id == result.program_id
    assert result.media_status == "pending_public_tenant_media_owner"
    assert result.video_activity_id != UUID(int=0)
    assert state.db.get(Program, source.id).tenant_id == state.operations
    global_program = state.db.get(Program, result.program_id)
    assert global_program is not None
    assert global_program.scope == CatalogScope.GLOBAL.value
    assert global_program.slug == AUTHORITY_CLOSERS_FREE_COURSE_SLUG
    adoption = await application.adopt_existing(
        actor=actor,
        source_program_id=source.id,
        command_id=uuid4(),
        reason="Adopt the reviewed staging Free Course without changing progress",
    )
    adoption_replay = await application.adopt_existing(
        actor=actor,
        source_program_id=source.id,
        command_id=adoption.command_id,
        reason="Adopt the reviewed staging Free Course without changing progress",
    )
    assert adoption.status == "adopted"
    assert adoption_replay.status == "replayed"
    assert adoption.video_activity_id == result.video_activity_id
    assert adoption.program_id == result.program_id
    with pytest.raises(FreeCoursePublicationConflict):
        await application.adopt_existing(
            actor=actor,
            source_program_id=source.id,
            command_id=result.command_id,
            reason="A publication command cannot be reused for adoption",
        )


async def test_publication_rejects_cross_tenant_actor_before_copy(state) -> None:
    await _grant_publication_capabilities(state)
    source = _source_course(state)
    actor = replace(
        state.actor,
        tenant_id=state.other,
        permissions=ROLE_PERMISSIONS["owner"],
    )
    application = FreeCoursePublicationApplication(
        PublicationSession(state.db),
        operations_tenant_id=state.operations,
        public_tenant_id=uuid4(),
    )

    with pytest.raises(FreeCoursePublicationError, match="operations tenant"):
        await application.apply(
            actor=actor,
            source_program_id=source.id,
            command_id=uuid4(),
            reason="Cross-tenant attempt",
        )


async def test_publication_records_review_and_publishes_draft_source(state) -> None:
    await _grant_publication_capabilities(state)
    source = _source_course(state, publish=False)
    actor = replace(
        state.actor,
        tenant_id=state.operations,
        permissions=ROLE_PERMISSIONS["owner"],
    )
    application = FreeCoursePublicationApplication(
        PublicationSession(state.db),
        operations_tenant_id=state.operations,
        public_tenant_id=state.other,
    )

    with pytest.raises(FreeCoursePublicationError, match="review evidence"):
        await application.apply(
            actor=actor,
            source_program_id=source.id,
            command_id=uuid4(),
            reason="Publication requires the reviewed source",
        )
    result = await application.apply(
        actor=actor,
        source_program_id=source.id,
        command_id=uuid4(),
        reason="Publication requires the reviewed source",
        source_ref="coach:dipak:big-buck-bunny-4k",
        release_id=RELEASE,
        reviewed_at=NOW,
    )
    source_version = state.db.query(ProgramVersion).filter_by(program_id=source.id).one()
    assert result.status == "published"
    assert source_version.status == ProgramVersionStatus.PUBLISHED.value
    assert source_version.content_source_ref == "coach:dipak:big-buck-bunny-4k"
    assert source_version.content_reviewed_by == f"person:{state.manager}"


async def test_publication_command_id_cannot_be_reused_for_another_source(state) -> None:
    await _grant_publication_capabilities(state)
    source = _source_course(state)
    actor = replace(
        state.actor,
        tenant_id=state.operations,
        permissions=ROLE_PERMISSIONS["owner"],
    )
    application = FreeCoursePublicationApplication(
        PublicationSession(state.db),
        operations_tenant_id=state.operations,
        public_tenant_id=state.other,
        clock=lambda: NOW,
    )
    command_id = uuid4()
    result = await application.apply(
        actor=actor,
        source_program_id=source.id,
        command_id=command_id,
        reason="Approved initial public Free Course publication",
    )
    other_source = uuid4()
    with pytest.raises(FreeCoursePublicationConflict):
        await application.apply(
            actor=actor,
            source_program_id=other_source,
            command_id=command_id,
            reason="Approved initial public Free Course publication",
        )
    assert result.command_id == command_id


async def test_publication_refuses_existing_global_course_without_mutation(state) -> None:
    await _grant_publication_capabilities(state)
    source = _source_course(state)
    service = CatalogService(SqlAlchemyCatalogStore(state.db), clock=lambda: NOW)
    service.create_program(
        tenant_id=None,
        scope=CatalogScope.GLOBAL,
        slug=AUTHORITY_CLOSERS_FREE_COURSE_SLUG,
        title="Existing staging Free Course",
        program_id=uuid4(),
        now=NOW,
    )
    actor = replace(
        state.actor,
        tenant_id=state.operations,
        permissions=ROLE_PERMISSIONS["owner"],
    )
    application = FreeCoursePublicationApplication(
        PublicationSession(state.db),
        operations_tenant_id=state.operations,
        public_tenant_id=state.other,
    )

    with pytest.raises(FreeCoursePublicationConflict, match="already occupied"):
        await application.apply(
            actor=actor,
            source_program_id=source.id,
            command_id=uuid4(),
            reason="Do not replace the existing global course",
        )
    source_version = state.db.query(ProgramVersion).filter_by(program_id=source.id).one()
    assert source_version.status == ProgramVersionStatus.PUBLISHED.value


async def test_ready_media_promotion_copies_and_binds_without_source_mutation(state) -> None:
    await _grant_publication_capabilities(state)
    source = _source_course(state)
    actor = replace(
        state.actor,
        tenant_id=state.operations,
        permissions=ROLE_PERMISSIONS["owner"],
    )
    publication = FreeCoursePublicationApplication(
        PublicationSession(state.db),
        operations_tenant_id=state.operations,
        public_tenant_id=state.academy,
        clock=lambda: NOW,
    )
    publication_result = await publication.apply(
        actor=actor,
        source_program_id=source.id,
        command_id=uuid4(),
        reason="Approved initial public Free Course publication",
    )
    target_activity = state.db.query(Activity).filter_by(
        program_id=publication_result.program_id,
        program_version_id=publication_result.program_version_id,
        kind="VIDEO",
    ).one()

    signer = MediaSigner(b"free-course-media-test-signing-key-32")
    storage = InMemoryPrivateObjectStorage(signer)
    service = MediaService(
        storage=storage,
        signer=signer,
        webhook_secret=b"free-course-media-test-webhook-secret",
    )
    source_asset_id, source_version_id = uuid4(), uuid4()
    source_prefix = (
        f"tenants/{state.operations}/media/video/{source_asset_id}/{source_version_id}/"
    )
    source_body = b"verified source bytes"
    source_metadata = storage.put(
        object_key=source_prefix + "original",
        body=source_body,
        content_type="video/mp4",
    )
    rendition_metadata = storage.put(
        object_key=source_prefix + "renditions/progressive.mp4",
        body=source_body,
        content_type="video/mp4",
    )
    hls_master_key = source_prefix + "renditions/hls/master.m3u8"
    hls_variant_key = source_prefix + "renditions/hls/variant/index.m3u8"
    hls_segment_key = source_prefix + "renditions/hls/variant/segments/seg-000.ts"
    storage.put(
        object_key=hls_master_key,
        body=(
            b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100000\n"
            b"variant/index.m3u8\n"
        ),
        content_type="application/vnd.apple.mpegurl",
    )
    storage.put(
        object_key=hls_variant_key,
        body=(
            b"#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:4,\n"
            b"segments/seg-000.ts\n#EXT-X-ENDLIST\n"
        ),
        content_type="application/vnd.apple.mpegurl",
    )
    storage.put(
        object_key=hls_segment_key,
        body=b"verified transport segment",
        content_type="video/mp2t",
    )
    state.db.add(
        MediaAsset(
            id=source_asset_id,
            tenant_id=state.operations,
            owner_person_id=state.manager,
            purpose=MediaPurpose.VIDEO.value,
            state=MediaLifecycle.READY.value,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    state.db.add(
        MediaVersion(
            id=source_version_id,
            tenant_id=state.operations,
            asset_id=source_asset_id,
            version_number=1,
            purpose=MediaPurpose.VIDEO.value,
            state=MediaLifecycle.READY.value,
            content_type="video/mp4",
            declared_bytes=len(source_body),
            actual_bytes=source_metadata.content_length,
            checksum_sha256=source_metadata.checksum_sha256,
            object_key=source_metadata.object_key,
            storage_version_id=source_metadata.storage_version_id,
            duration_seconds=12.0,
            width=3840,
            height=2160,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    state.db.flush()
    state.db.get(MediaAsset, source_asset_id).current_version_id = source_version_id
    state.db.add(
        MediaRendition(
            id=uuid4(),
            tenant_id=state.operations,
            asset_id=source_asset_id,
            version_id=source_version_id,
            protocol="progressive",
            content_type="video/mp4",
            object_key=rendition_metadata.object_key,
            width=3840,
            height=2160,
        )
    )
    state.db.add(
        MediaRendition(
            id=uuid4(),
            tenant_id=state.operations,
            asset_id=source_asset_id,
            version_id=source_version_id,
            protocol="hls",
            content_type="application/vnd.apple.mpegurl",
            object_key=hls_master_key,
            width=3840,
            height=2160,
        )
    )
    state.db.flush()

    previous_asset_id, previous_version_id = uuid4(), uuid4()
    previous_key = (
        f"tenants/{state.academy}/media/video/{previous_asset_id}/{previous_version_id}/original"
    )
    previous_metadata = storage.put(
        object_key=previous_key,
        body=b"staging fixture bytes",
        content_type="video/mp4",
    )
    state.db.add(
        MediaAsset(
            id=previous_asset_id,
            tenant_id=state.academy,
            owner_person_id=state.manager,
            purpose=MediaPurpose.VIDEO.value,
            state=MediaLifecycle.READY.value,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    state.db.add(
        MediaVersion(
            id=previous_version_id,
            tenant_id=state.academy,
            asset_id=previous_asset_id,
            version_number=1,
            purpose=MediaPurpose.VIDEO.value,
            state=MediaLifecycle.READY.value,
            content_type="video/mp4",
            declared_bytes=previous_metadata.content_length,
            actual_bytes=previous_metadata.content_length,
            checksum_sha256=previous_metadata.checksum_sha256,
            object_key=previous_key,
            storage_version_id=previous_metadata.storage_version_id,
            duration_seconds=5.0,
            width=1920,
            height=1080,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    state.db.flush()
    state.db.get(MediaAsset, previous_asset_id).current_version_id = previous_version_id
    previous_binding = ActivityMediaBinding(
        id=uuid4(),
        tenant_id=state.academy,
        activity_id=target_activity.id,
        module_id=target_activity.module_id,
        program_version_id=target_activity.program_version_id,
        program_id=target_activity.program_id,
        program_scope=CatalogScope.GLOBAL.value,
        program_owner_key=UUID(int=0),
        activity_version=f"activity:{target_activity.id}",
        asset_id=previous_asset_id,
        version_id=previous_version_id,
        state="approved",
        approval_reference="existing staging fixture",
        approved_by_person_id=state.manager,
        approved_at=NOW,
        idempotency_key="existing-staging-binding",
        request_fingerprint="0" * 64,
        created_at=NOW,
        updated_at=NOW,
    )
    state.db.add(previous_binding)
    state.db.flush()

    promotion = FreeCourseMediaPromotionApplication(
        PublicationSession(state.db),
        service=service,
        operations_tenant_id=state.operations,
        public_tenant_id=state.academy,
        clock=lambda: NOW,
    )
    command_id = uuid4()
    result = await promotion.apply(
        actor=actor,
        publication_command_id=publication_result.command_id,
        command_id=command_id,
        activity_id=target_activity.id,
        source_asset_id=source_asset_id,
        source_version_id=source_version_id,
        media_owner_person_id=state.manager,
        approval_reference="AC-FREE-COURSE-PROMOTION:test",
        supersedes_binding_id=previous_binding.id,
    )
    replay = await promotion.apply(
        actor=actor,
        publication_command_id=publication_result.command_id,
        command_id=command_id,
        activity_id=target_activity.id,
        source_asset_id=source_asset_id,
        source_version_id=source_version_id,
        media_owner_person_id=state.manager,
        approval_reference="AC-FREE-COURSE-PROMOTION:test",
        supersedes_binding_id=previous_binding.id,
    )

    target_asset = state.db.get(MediaAsset, result.asset_id)
    target_version = state.db.get(MediaVersion, result.version_id)
    assert result.media_status == "ready_public_tenant_media_bound"
    assert replay.status == "replayed"
    assert target_asset is not None and target_asset.owner_person_id == state.manager
    assert target_version is not None and target_version.state == MediaLifecycle.READY.value
    assert state.db.get(MediaAsset, source_asset_id).tenant_id == state.operations
    target_prefix = (
        f"tenants/{state.academy}/media/video/{result.asset_id}/{result.version_id}/"
    )
    assert storage.head(target_prefix + "renditions/hls/master.m3u8") is not None
    assert storage.head(target_prefix + "renditions/hls/variant/index.m3u8") is not None
    assert storage.head(target_prefix + "renditions/hls/variant/segments/seg-000.ts") is not None
    assert previous_binding.state == "superseded"
    current_binding = state.db.get(ActivityMediaBinding, result.binding_id)
    assert current_binding is not None
    assert current_binding.supersedes_binding_id == previous_binding.id
