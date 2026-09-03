from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
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
from ac_platform.media.errors import MediaConflict, MediaForbidden, MediaStorageUnavailable
from ac_platform.media.models import (
    CaptionKind,
    CaptionState,
    MediaCaptionTrack,
    MediaLifecycle,
    MediaPurpose,
    MediaVersion,
)
from ac_platform.media.processing import ProcessedRendition, ProcessingResult, TestCopyProcessor
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
            provider_asset_id=provider_asset_id,
            duration_seconds=duration_seconds,
        ),
        idempotency_key=f"complete-{key}",
    )
    return intent


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


def test_provider_webhook_requires_signature_and_replay_is_idempotent(
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
    applied, applied_replayed = service.handle_webhook(database, "video", payload, signature)
    replayed, replayed_flag = service.handle_webhook(database, "video", payload, signature)
    assert applied.id == replayed.id == intent.media_version_id
    assert applied.state is MediaLifecycle.READY
    assert applied_replayed is False
    assert replayed_flag is True
