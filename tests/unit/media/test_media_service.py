from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ac_platform.db.models import model_metadata
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.media.api_contracts import (
    CaptionCreateRequest,
    MediaHeartbeatRequest,
    PlaybackRequest,
    RenditionWebhook,
    UploadCompleteRequest,
    UploadIntentRequest,
    VideoWebhookRequest,
)
from ac_platform.media.config import MediaProviderConfig
from ac_platform.media.errors import (
    MediaConfigurationError,
    MediaConflict,
    MediaForbidden,
    MediaQuotaExceeded,
    MediaStorageUnavailable,
)
from ac_platform.media.lifecycle import (
    InMemoryMediaLifecycleHooks,
    MediaRetentionPolicy,
)
from ac_platform.media.models import (
    CaptionKind,
    CaptionState,
    MediaCaptionTrack,
    MediaLifecycle,
    MediaPurpose,
    MediaVersion,
)
from ac_platform.media.policy import SignedMediaDeliveryPort
from ac_platform.media.processing import (
    ProcessedRendition,
    ProcessingQuota,
    ProcessingResult,
    TestCopyProcessor,
)
from ac_platform.media.processing import (
    TestTranscodingProcessor as LocalTranscodingProcessor,
)
from ac_platform.media.scanner import SignatureContentScanner
from ac_platform.media.service import MediaService
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import InMemoryPrivateObjectStorage, PrivateObjectStorage
from ac_platform.tenancy.models import Membership, MembershipRole, Tenant


class BadMimeProcessor(TestCopyProcessor):
    def process(
        self,
        *,
        storage: PrivateObjectStorage,
        version_id: UUID,
        purpose: MediaPurpose,
        source_key: str,
        content_type: str,
        crop: dict[str, object] | None,
    ) -> ProcessingResult:
        result = super().process(
            storage=storage,
            version_id=version_id,
            purpose=purpose,
            source_key=source_key,
            content_type=content_type,
            crop=crop,
        )
        if not result.renditions:
            return result
        rendition = result.renditions[0]
        return ProcessingResult(
            renditions=(
                ProcessedRendition(
                    id=rendition.id,
                    protocol=rendition.protocol,
                    content_type="text/html",
                    object_key=rendition.object_key,
                    width=rendition.width,
                    height=rendition.height,
                    bitrate_kbps=rendition.bitrate_kbps,
                ),
            )
        )


class _TestActivationVerifier:
    def verify(
        self,
        *,
        config_fingerprint: str,
        governance_reference: str,
        media_gap_reference: str,
    ) -> bool:
        del config_fingerprint
        return governance_reference == "AC-GOV-AUD-001" and media_gap_reference == "GAP-MEDIA-001"


def _test_media_config() -> MediaProviderConfig:
    return MediaProviderConfig(
        environment="test",
        enabled=True,
        provider="minio",
        endpoint_url="https://minio.test",
        bucket="ac-media",
        region="us-east-1",
        access_key_id="access-key",
        secret_access_key="x" * 32,
        delivery_origin="https://media.test",
        allowed_origins=("https://app.test",),
        governance_reference="AC-GOV-AUD-001",
        media_gap_reference="GAP-MEDIA-001",
        approved_endpoint_hosts=("minio.test",),
    )


@pytest.fixture
def harness() -> tuple[Session, ActorContext, MediaService, InMemoryPrivateObjectStorage]:
    engine = create_engine("sqlite:///:memory:")
    model_metadata().create_all(engine)
    database = Session(engine)
    tenant_id = uuid4()
    person_id = uuid4()
    database.add_all(
        [
            Tenant(id=tenant_id, slug=f"tenant-{tenant_id}", name="Tenant"),
            Person(
                id=person_id,
                email=f"{person_id}@example.com",
                email_verified_at=datetime.now(UTC),
            ),
            Membership(
                tenant_id=tenant_id,
                person_id=person_id,
                role=MembershipRole.OWNER.value,
            ),
        ]
    )
    database.commit()
    actor = ActorContext(
        person_id=person_id,
        session_id=uuid4(),
        tenant_id=tenant_id,
        permissions=frozenset({"catalog_write"}),
    )
    signer = MediaSigner(hashlib.sha256(b"unit-test-media-signer").digest())
    storage = InMemoryPrivateObjectStorage(signer)
    service = MediaService(
        storage=storage,
        signer=signer,
        webhook_secret=hashlib.sha256(b"unit-test-media-webhook").digest(),
        scanner=SignatureContentScanner(),
        processor=TestCopyProcessor(),
        delivery_port=SignedMediaDeliveryPort(
            signer=signer,
            delivery_origin="https://media.test",
        ),
        media_config=_test_media_config(),
        activation_verifier=_TestActivationVerifier(),
    )
    try:
        yield database, actor, service, storage
    finally:
        database.close()
        engine.dispose()


def _upload(
    database: Session,
    actor: ActorContext,
    service: MediaService,
    storage: InMemoryPrivateObjectStorage,
    *,
    purpose: MediaPurpose,
    body: bytes,
    content_type: str,
    key: str,
    asset_id=None,
    provider_asset_id: str | None = None,
    duration_seconds: float | None = None,
):
    digest = hashlib.sha256(body).hexdigest()
    intent = service.create_upload_intent(
        database,
        actor,
        UploadIntentRequest(
            purpose=purpose,
            filename="client-name.bin",
            content_type=content_type,
            content_length=len(body),
            checksum_sha256=digest,
            asset_id=asset_id,
        ),
        idempotency_key=key,
    )
    storage.put(object_key=intent.object_key, body=body, content_type=content_type)
    service.complete_upload(
        database,
        actor,
        intent.upload_id,
        UploadCompleteRequest(
            actual_bytes=len(body),
            checksum_sha256=digest,
            duration_seconds=duration_seconds,
        ),
        idempotency_key=f"complete-{key}",
    )
    if provider_asset_id is not None:
        version = database.get(MediaVersion, intent.media_version_id)
        assert version is not None
        # Provider asset identifiers are written only by the trusted
        # integration boundary, never accepted from UploadCompleteRequest.
        version.provider_asset_id = provider_asset_id
        database.flush()
    return intent


def test_provider_webhook_requires_external_activation_verifier(
    harness: tuple[Session, ActorContext, MediaService, InMemoryPrivateObjectStorage],
) -> None:
    database, _, service, _ = harness
    service.media_config = None

    with pytest.raises(MediaConfigurationError, match="not activated"):
        service.handle_webhook(database, "video", b"{}", "0" * 64)


def test_upload_completion_rejects_client_provider_asset_identifier() -> None:
    with pytest.raises(ValueError):
        UploadCompleteRequest.model_validate({"provider_asset_id": "client-controlled"})


def test_upload_completion_rejects_duration_over_processing_quota(
    harness: tuple[Session, ActorContext, MediaService, InMemoryPrivateObjectStorage],
) -> None:
    database, actor, service, storage = harness
    body = b"\x00" * 16
    digest = hashlib.sha256(body).hexdigest()
    intent = service.create_upload_intent(
        database,
        actor,
        UploadIntentRequest(
            purpose=MediaPurpose.VIDEO,
            filename="video.mp4",
            content_type="video/mp4",
            content_length=len(body),
            checksum_sha256=digest,
        ),
        idempotency_key="duration-bound",
    )
    storage.put(object_key=intent.object_key, body=body, content_type="video/mp4")

    with pytest.raises(MediaQuotaExceeded, match="duration"):
        service.complete_upload(
            database,
            actor,
            intent.upload_id,
            UploadCompleteRequest(duration_seconds=4 * 60 * 60 + 1),
            idempotency_key="duration-bound-complete",
        )


def test_upload_scan_process_and_supersession_are_durable(
    harness: tuple[Session, ActorContext, MediaService, InMemoryPrivateObjectStorage],
) -> None:
    database, actor, service, storage = harness
    body = b"\x89PNG\r\n\x1a\npayload"
    first = _upload(
        database,
        actor,
        service,
        storage,
        purpose=MediaPurpose.AVATAR,
        body=body,
        content_type="image/png",
        key="avatar-1",
    )
    ready = service.process_version(database, actor, first.media_version_id)
    assert ready.state is MediaLifecycle.READY
    assert len(ready.current_version.avatar_variants) == 3
    assert (
        "object_key" not in ready.model_dump(mode="json")["current_version"]["avatar_variants"][0]
    )

    replay = service.create_upload_intent(
        database,
        actor,
        UploadIntentRequest(
            purpose=MediaPurpose.AVATAR,
            filename="client-name.bin",
            content_type="image/png",
            content_length=len(body),
            checksum_sha256=hashlib.sha256(body).hexdigest(),
        ),
        idempotency_key="avatar-1",
    )
    assert replay.upload_id == first.upload_id

    second = _upload(
        database,
        actor,
        service,
        storage,
        purpose=MediaPurpose.AVATAR,
        body=body,
        content_type="image/png",
        key="avatar-2",
        asset_id=first.media_id,
    )
    result = service.process_version(database, actor, second.media_version_id)
    assert result.current_version_id == second.media_version_id
    versions = database.scalars(
        select(MediaVersion).where(MediaVersion.asset_id == first.media_id)
    ).all()
    assert len(versions) == 2
    assert {version.state for version in versions} == {MediaLifecycle.READY.value}


def test_processing_tracks_hls_children_for_retention(
    harness: tuple[Session, ActorContext, MediaService, InMemoryPrivateObjectStorage],
) -> None:
    database, actor, service, storage = harness
    body = b"\x00\x00\x00\x18ftypmp42payload"
    intent = _upload(
        database,
        actor,
        service,
        storage,
        purpose=MediaPurpose.VIDEO,
        body=body,
        content_type="video/mp4",
        key="video-hls-lifecycle",
        duration_seconds=30,
    )
    hooks = InMemoryMediaLifecycleHooks()
    processing_service = MediaService(
        storage=storage,
        signer=service.signer,
        webhook_secret=service.webhook_secret,
        scanner=SignatureContentScanner(),
        processor=LocalTranscodingProcessor(include_progressive=False),
        lifecycle_hooks=hooks,
        retention_policy=MediaRetentionPolicy(
            policy_id="media-test-retention",
            retired_after=timedelta(days=1),
            delete_objects=True,
        ),
    )
    processing_service.process_version(database, actor, intent.media_version_id)
    version = database.get(MediaVersion, intent.media_version_id)
    assert version is not None
    reference = processing_service._object_reference(version)
    inventory = {item.object_key for item in hooks.object_references(reference)}
    playlist = f"{version.object_key}/renditions/hls/360p/index.m3u8"
    segment = f"{version.object_key}/renditions/hls/360p/segment-000.ts"
    assert {playlist, segment}.issubset(inventory)

    processing_service.retire(database, actor, intent.media_id)
    scheduled = {
        event.reference.object_key
        for event in hooks.events
        if event.action.value == "delete_scheduled"
    }
    assert {playlist, segment}.issubset(scheduled)


def test_profile_avatar_returns_scoped_ephemeral_delivery_and_pending_replacement(
    harness: tuple[Session, ActorContext, MediaService, InMemoryPrivateObjectStorage],
) -> None:
    database, actor, service, storage = harness
    body = b"\x89PNG\r\n\x1a\navatar"
    first = _upload(
        database,
        actor,
        service,
        storage,
        purpose=MediaPurpose.AVATAR,
        body=body,
        content_type="image/png",
        key="profile-avatar-1",
    )
    service.process_version(database, actor, first.media_version_id)

    current = service.get_profile_avatar(database, actor)
    assert current.avatar is not None
    assert current.avatar.asset_id == first.media_id
    assert current.avatar.version_id == first.media_version_id
    assert current.avatar.state is MediaLifecycle.READY
    assert current.avatar.delivery_url is not None
    assert current.avatar.delivery_url.startswith("https://")
    assert "object_key" not in current.avatar.model_dump(mode="json")
    assert current.pending is None

    replacement = service.create_upload_intent(
        database,
        actor,
        UploadIntentRequest(
            purpose=MediaPurpose.AVATAR,
            filename="replacement.png",
            content_type="image/png",
            content_length=len(body),
            checksum_sha256=hashlib.sha256(body).hexdigest(),
            asset_id=first.media_id,
            supersedes_version_id=first.media_version_id,
        ),
        idempotency_key="profile-avatar-2",
    )
    pending = service.get_profile_avatar(database, actor)
    assert pending.avatar is not None
    assert pending.avatar.version_id == first.media_version_id
    assert pending.pending is not None
    assert pending.pending.version_id == replacement.media_version_id
    assert pending.pending.state is MediaLifecycle.UPLOADING


def test_profile_avatar_never_discloses_another_person_or_tenant_avatar(
    harness: tuple[Session, ActorContext, MediaService, InMemoryPrivateObjectStorage],
) -> None:
    database, actor, service, storage = harness
    body = b"\x89PNG\r\n\x1a\nprivate-avatar"
    first = _upload(
        database,
        actor,
        service,
        storage,
        purpose=MediaPurpose.AVATAR,
        body=body,
        content_type="image/png",
        key="private-avatar",
    )
    service.process_version(database, actor, first.media_version_id)

    other = Person(
        id=uuid4(),
        email=f"{uuid4()}@example.com",
        email_verified_at=datetime.now(UTC),
    )
    database.add(other)
    database.add(
        Membership(
            tenant_id=actor.tenant_id,
            person_id=other.id,
            role=MembershipRole.LEARNER.value,
        )
    )
    database.commit()
    other_actor = ActorContext(
        person_id=other.id,
        session_id=uuid4(),
        tenant_id=actor.tenant_id,
        permissions=frozenset(),
    )

    result = service.get_profile_avatar(database, other_actor)
    assert result.avatar is None
    assert result.pending is None

    other_tenant_id = uuid4()
    database.add(Tenant(id=other_tenant_id, slug=f"tenant-{other_tenant_id}", name="Other Tenant"))
    database.add(
        Membership(
            tenant_id=other_tenant_id,
            person_id=actor.person_id,
            role=MembershipRole.LEARNER.value,
        )
    )
    database.commit()
    cross_tenant_actor = ActorContext(
        person_id=actor.person_id,
        session_id=uuid4(),
        tenant_id=other_tenant_id,
        permissions=frozenset(),
    )

    cross_tenant_result = service.get_profile_avatar(database, cross_tenant_actor)
    assert cross_tenant_result.avatar is None
    assert cross_tenant_result.pending is None


def test_processor_rendition_mime_is_verified_before_ready(
    harness: tuple[Session, ActorContext, MediaService, InMemoryPrivateObjectStorage],
) -> None:
    database, actor, service, storage = harness
    body = b"\x00\x00\x00\x18ftypmp42payload"
    intent = _upload(
        database,
        actor,
        service,
        storage,
        purpose=MediaPurpose.VIDEO,
        body=body,
        content_type="video/mp4",
        key="video-bad-mime",
        duration_seconds=60,
    )
    bad_service = MediaService(
        storage=storage,
        signer=service.signer,
        webhook_secret=service.webhook_secret,
        scanner=SignatureContentScanner(),
        processor=BadMimeProcessor(),
    )
    with pytest.raises(MediaConflict):
        bad_service.process_version(database, actor, intent.media_version_id)
    version = database.get(MediaVersion, intent.media_version_id)
    assert version is not None
    assert version.state == MediaLifecycle.FAILED.value


def test_video_processing_without_a_validated_duration_cannot_be_ready(
    harness: tuple[Session, ActorContext, MediaService, InMemoryPrivateObjectStorage],
) -> None:
    database, actor, service, storage = harness
    body = b"\x00\x00\x00\x18ftypmp42payload"
    intent = _upload(
        database,
        actor,
        service,
        storage,
        purpose=MediaPurpose.VIDEO,
        body=body,
        content_type="video/mp4",
        key="video-without-duration",
        duration_seconds=30,
    )
    service.processor = TestCopyProcessor(measured_duration_seconds=None)  # type: ignore[assignment]

    version = database.get(MediaVersion, intent.media_version_id)
    assert version is not None
    assert version.duration_seconds is None

    with pytest.raises(MediaConflict, match="invalid output"):
        service.process_version(database, actor, intent.media_version_id)

    version = database.get(MediaVersion, intent.media_version_id)
    assert version is not None
    assert version.state == MediaLifecycle.FAILED.value


def test_failed_output_cleanup_is_recorded_for_retry(
    harness: tuple[Session, ActorContext, MediaService, InMemoryPrivateObjectStorage],
) -> None:
    database, actor, service, storage = harness
    body = b"\x00\x00\x00\x18ftypmp42payload"
    intent = _upload(
        database,
        actor,
        service,
        storage,
        purpose=MediaPurpose.VIDEO,
        body=body,
        content_type="video/mp4",
        key="video-cleanup-retry",
        duration_seconds=60,
    )

    class FailingDeleteStorage(InMemoryPrivateObjectStorage):
        def delete(self, object_key: str) -> None:
            del object_key
            raise RuntimeError("cleanup unavailable")

    failing_storage = FailingDeleteStorage(service.signer)
    source = storage.read(intent.object_key)
    failing_storage.put(
        object_key=intent.object_key,
        body=source,
        content_type="video/mp4",
    )
    hooks = InMemoryMediaLifecycleHooks()

    class FailingProcessor:
        def process(self, **kwargs: object) -> ProcessingResult:
            storage_adapter = kwargs["storage"]
            source_key = kwargs["source_key"]
            assert isinstance(storage_adapter, FailingDeleteStorage)
            assert isinstance(source_key, str)
            storage_adapter.put(
                object_key=f"{source_key}/renditions/orphan.mp4",
                body=b"partial",
                content_type="video/mp4",
            )
            raise RuntimeError("processor failed")

    processing_service = MediaService(
        storage=failing_storage,
        signer=service.signer,
        webhook_secret=service.webhook_secret,
        scanner=SignatureContentScanner(),
        processor=FailingProcessor(),
        lifecycle_hooks=hooks,
    )
    with pytest.raises(MediaConflict):
        processing_service.process_version(database, actor, intent.media_version_id)

    cleanup_events = [
        event for event in hooks.events if event.action.value == "output_cleanup_retryable"
    ]
    assert cleanup_events
    assert cleanup_events[-1].reason_code == "MEDIA_OUTPUT_CLEANUP_FAILED"


def test_service_cleans_prefix_outputs_when_processor_fails_before_returning(
    harness: tuple[Session, ActorContext, MediaService, InMemoryPrivateObjectStorage],
) -> None:
    database, actor, service, storage = harness
    body = b"\x00\x00\x00\x18ftypmp42payload"
    intent = _upload(
        database,
        actor,
        service,
        storage,
        purpose=MediaPurpose.VIDEO,
        body=body,
        content_type="video/mp4",
        key="video-prefix-cleanup",
        duration_seconds=60,
    )

    class FailingProcessor:
        def process(self, **kwargs: object) -> ProcessingResult:
            storage_adapter = kwargs["storage"]
            source_key = kwargs["source_key"]
            assert isinstance(storage_adapter, InMemoryPrivateObjectStorage)
            assert isinstance(source_key, str)
            storage_adapter.put(
                object_key=f"{source_key}/renditions/orphan.mp4",
                body=b"partial",
                content_type="video/mp4",
            )
            raise RuntimeError("processor failed before returning a result")

    service.processor = FailingProcessor()  # type: ignore[assignment]
    with pytest.raises(MediaConflict):
        service.process_version(database, actor, intent.media_version_id)

    assert storage.head(f"{intent.object_key}/renditions/orphan.mp4") is None


def test_provider_ready_callback_remains_unavailable_without_internal_measurement(
    harness: tuple[Session, ActorContext, MediaService, InMemoryPrivateObjectStorage],
) -> None:
    database, actor, service, storage = harness
    hooks = InMemoryMediaLifecycleHooks()
    service = MediaService(
        storage=storage,
        signer=service.signer,
        webhook_secret=service.webhook_secret,
        scanner=SignatureContentScanner(),
        processor=TestCopyProcessor(),
        lifecycle_hooks=hooks,
        media_config=_test_media_config(),
        activation_verifier=_TestActivationVerifier(),
    )
    body = b"\x00\x00\x00\x18ftypmp42payload"
    intent = _upload(
        database,
        actor,
        service,
        storage,
        purpose=MediaPurpose.VIDEO,
        body=body,
        content_type="video/mp4",
        key="video-webhook-hls",
        provider_asset_id="provider-hls-1",
        duration_seconds=30,
    )
    master_key = f"{intent.object_key}/renditions/master.m3u8"
    playlist_key = f"{intent.object_key}/renditions/hls/360p/index.m3u8"
    segment_key = f"{intent.object_key}/renditions/hls/360p/segment-000.ts"
    storage.put(
        object_key=master_key,
        body=b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nhls/360p/index.m3u8\n",
        content_type="application/vnd.apple.mpegurl",
    )
    storage.put(
        object_key=playlist_key,
        body=b"#EXTM3U\n#EXTINF:1,\nsegment-000.ts\n#EXT-X-ENDLIST\n",
        content_type="application/vnd.apple.mpegurl",
    )
    storage.put(object_key=segment_key, body=b"segment", content_type="video/mp2t")
    payload = (
        VideoWebhookRequest(
            provider_event_id="provider-hls-event-1",
            event_type="video.ready",
            media_version_id=intent.media_version_id,
            provider_asset_id="provider-hls-1",
            state=MediaLifecycle.READY,
            renditions=[
                RenditionWebhook(
                    id=uuid4(),
                    protocol="hls",
                    content_type="application/vnd.apple.mpegurl",
                    object_key=master_key,
                )
            ],
        )
        .model_dump_json()
        .encode()
    )
    signature = hmac.new(service.webhook_secret, payload, hashlib.sha256).hexdigest()

    with pytest.raises(MediaConflict, match="independent internal duration"):
        service.handle_webhook(database, "video", payload, signature)

    version = database.get(MediaVersion, intent.media_version_id)
    assert version is not None
    assert version.state == MediaLifecycle.PROCESSING.value
    tracked = hooks.object_references(service._object_reference(version))
    assert {item.object_key for item in tracked} == {version.object_key}


def test_media_service_rejects_insecure_adapter_urls(
    harness: tuple[Session, ActorContext, MediaService, InMemoryPrivateObjectStorage],
) -> None:
    _, _, service, _ = harness
    with pytest.raises(MediaStorageUnavailable):
        service._secure_media_url("http://media.test/object", description="delivery")


def test_playback_grant_is_actor_scoped_and_heartbeat_is_resume_only(
    harness: tuple[Session, ActorContext, MediaService, InMemoryPrivateObjectStorage],
) -> None:
    database, actor, service, storage = harness
    body = b"\x00\x00\x00\x18ftypmp42payload"
    intent = _upload(
        database,
        actor,
        service,
        storage,
        purpose=MediaPurpose.VIDEO,
        body=body,
        content_type="video/mp4",
        key="video-1",
        duration_seconds=60,
    )
    service.process_version(database, actor, intent.media_version_id)
    playback = service.create_playback(
        database,
        actor,
        intent.media_id,
        PlaybackRequest(),
        idempotency_key="playback-1",
    )
    playback_retry = service.create_playback(
        database,
        actor,
        intent.media_id,
        PlaybackRequest(),
        idempotency_key="playback-1",
    )
    assert playback_retry.session_id == playback.session_id
    assert playback_retry.access_token == playback.access_token
    heartbeat = service.heartbeat(
        database,
        actor,
        intent.media_id,
        MediaHeartbeatRequest(
            session_id=playback.session_id,
            position_seconds=10,
            played_from_seconds=0,
            played_to_seconds=10,
            client_event_id="event-1",
            sequence=0,
        ),
        playback.access_token,
    )
    assert heartbeat.accepted is True
    assert heartbeat.position_seconds == 10
    duplicate = service.heartbeat(
        database,
        actor,
        intent.media_id,
        MediaHeartbeatRequest(
            session_id=playback.session_id,
            position_seconds=10,
            played_from_seconds=0,
            played_to_seconds=10,
            client_event_id="event-1",
            sequence=0,
        ),
        playback.access_token,
    )
    assert duplicate.accepted is False
    assert "completion" not in duplicate.model_dump()

    other = ActorContext(uuid4(), uuid4(), actor.tenant_id, frozenset())
    with pytest.raises(MediaForbidden):
        service.heartbeat(
            database,
            other,
            intent.media_id,
            MediaHeartbeatRequest(
                session_id=playback.session_id,
                position_seconds=11,
                played_from_seconds=10,
                played_to_seconds=11,
                client_event_id="event-2",
                sequence=1,
            ),
            playback.access_token,
        )


def test_caption_replacement_writes_private_content_and_supersedes_previous(
    harness: tuple[Session, ActorContext, MediaService, InMemoryPrivateObjectStorage],
) -> None:
    database, actor, service, storage = harness
    body = b"\x00\x00\x00\x18ftypmp42payload"
    intent = _upload(
        database,
        actor,
        service,
        storage,
        purpose=MediaPurpose.VIDEO,
        body=body,
        content_type="video/mp4",
        key="video-caption",
        duration_seconds=30,
    )
    service.process_version(database, actor, intent.media_version_id)
    request = CaptionCreateRequest(
        language="en", kind=CaptionKind.CAPTIONS, content_type="text/vtt", content="WEBVTT\n"
    )
    first = service.add_caption(
        database, actor, intent.media_id, request, idempotency_key="caption-1"
    )
    second = service.add_caption(
        database,
        actor,
        intent.media_id,
        request.model_copy(update={"content": "WEBVTT\n\n00:00.000 --> 00:01.000\nHi"}),
        idempotency_key="caption-2",
    )
    assert first.id != second.id
    rows = database.scalars(
        select(MediaCaptionTrack).where(MediaCaptionTrack.version_id == intent.media_version_id)
    ).all()
    assert {row.state for row in rows} == {CaptionState.READY.value, CaptionState.SUPERSEDED.value}
    assert storage.head(rows[-1].object_key) is not None


def test_caption_count_and_bytes_are_scanned_and_bounded(
    harness: tuple[Session, ActorContext, MediaService, InMemoryPrivateObjectStorage],
) -> None:
    database, actor, service, storage = harness
    service.processing_quota = ProcessingQuota(max_caption_tracks=1, max_caption_bytes=64)
    body = b"\x00\x00\x00\x18ftypmp42payload"
    intent = _upload(
        database,
        actor,
        service,
        storage,
        purpose=MediaPurpose.VIDEO,
        body=body,
        content_type="video/mp4",
        key="video-caption-quota",
        duration_seconds=30,
    )
    service.process_version(database, actor, intent.media_version_id)
    request = CaptionCreateRequest(
        language="en", kind=CaptionKind.CAPTIONS, content_type="text/vtt", content="WEBVTT\n"
    )
    service.add_caption(database, actor, intent.media_id, request, idempotency_key="caption-en")
    stored = database.scalars(
        select(MediaCaptionTrack).where(MediaCaptionTrack.version_id == intent.media_version_id)
    ).all()
    assert len(stored) == 1
    assert storage.head(stored[0].object_key) is not None

    with pytest.raises(MediaQuotaExceeded, match="caption count"):
        service.add_caption(
            database,
            actor,
            intent.media_id,
            request.model_copy(update={"language": "fr"}),
            idempotency_key="caption-fr",
        )


def test_provider_ready_webhook_cannot_use_provider_duration(
    harness: tuple[Session, ActorContext, MediaService, InMemoryPrivateObjectStorage],
) -> None:
    database, actor, service, storage = harness
    body = b"\x00\x00\x00\x18ftypmp42payload"
    intent = _upload(
        database,
        actor,
        service,
        storage,
        purpose=MediaPurpose.VIDEO,
        body=body,
        content_type="video/mp4",
        key="video-webhook",
        provider_asset_id="provider-1",
        duration_seconds=30,
    )
    rendition_key = f"{intent.object_key}/renditions/provider.mp4"
    storage.put(object_key=rendition_key, body=body, content_type="video/mp4")
    payload = (
        VideoWebhookRequest(
            provider_event_id="provider-event-1",
            event_type="video.ready",
            media_version_id=intent.media_version_id,
            provider_asset_id="provider-1",
            state=MediaLifecycle.READY,
            duration_seconds=30,
            renditions=[
                RenditionWebhook(
                    id=uuid4(),
                    protocol="progressive",
                    content_type="video/mp4",
                    object_key=rendition_key,
                )
            ],
        )
        .model_dump_json()
        .encode()
    )
    signature = hmac.new(service.webhook_secret, payload, hashlib.sha256).hexdigest()
    with pytest.raises(MediaForbidden):
        service.handle_webhook(database, "video", payload, "0" * 64)
    with pytest.raises(MediaConflict, match="independent internal duration"):
        service.handle_webhook(database, "video", payload, signature)
    version = database.get(MediaVersion, intent.media_version_id)
    assert version is not None
    assert version.state == MediaLifecycle.PROCESSING.value


def test_timestamped_provider_webhook_signature_is_fresh_and_body_bound(
    harness: tuple[Session, ActorContext, MediaService, InMemoryPrivateObjectStorage],
) -> None:
    _, _, service, _ = harness
    now = datetime.now(UTC).replace(microsecond=0)
    timestamp = int(now.timestamp())
    payload = b'{"provider_event_id":"event"}'
    signature = hmac.new(
        service.webhook_secret,
        f"{timestamp}.".encode("ascii") + payload,
        hashlib.sha256,
    ).hexdigest()

    assert service.verify_webhook_signature(payload, signature, timestamp=timestamp, now=now)
    assert not service.verify_webhook_signature(
        payload, signature, timestamp=timestamp - 301, now=now
    )
    assert not service.verify_webhook_signature(
        payload + b"!", signature, timestamp=timestamp, now=now
    )
