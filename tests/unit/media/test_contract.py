from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from ac_platform.media import (
    AuthorizedMediaVersion,
    CaptionTrackDescriptor,
    EphemeralMediaUrl,
    MediaAssetId,
    MediaAssetVersion,
    MediaAuthorizationContext,
    MediaAuthorizationMismatchError,
    MediaDeliveryDescriptor,
    MediaDeliveryKind,
    MediaDeliveryMetadata,
    MediaDeliveryPort,
    MediaExpiredError,
    MediaNotYetValidError,
    MediaOriginError,
    MediaPolicyDeniedError,
    MediaProcessingError,
    MediaRangeError,
    MediaUnavailableError,
    MediaUnsupportedError,
    MediaVersionId,
    PlaybackGrantDescriptor,
    PosterDescriptor,
    RenditionDescriptor,
    TranscriptDescriptor,
    TranscriptFormat,
    create_media_authorization_context,
    resolve_authorized_delivery,
)

NOW = datetime(2026, 9, 2, 12, tzinfo=UTC)
AUTHORIZATION = create_media_authorization_context(
    tenant_id="tenant-1",
    person_id="person-1",
    session_id="session-1",
)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "learner.localhost"])
def test_ephemeral_http_requires_explicit_loopback_opt_in(host):
    url = f"http://{host}:3100/v1/media/playback/fixture"
    with pytest.raises(ValueError):
        EphemeralMediaUrl(url)
    assert str(EphemeralMediaUrl(url, allow_loopback_http=True)) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://remote.example/video",
        "http://localhost.evil/video",
        "http://user@localhost:3100/video",
        "http://localhost:3100/video#fragment",
        "http://localhost:99999/video",
    ],
)
def test_loopback_opt_in_never_opens_remote_or_malformed_http(url):
    with pytest.raises(ValueError):
        EphemeralMediaUrl(url, allow_loopback_http=True)


def _request(
    *,
    authorization: MediaAuthorizationContext = AUTHORIZATION,
    activity_id: str = "activity-1",
    activity_version: str = "activity-v1",
    media_version: MediaAssetVersion | None = None,
) -> AuthorizedMediaVersion:
    return AuthorizedMediaVersion(
        authorization=authorization,
        activity_id=activity_id,
        activity_version=activity_version,
        media_version=media_version
        or MediaAssetVersion(
            asset_id=MediaAssetId("lesson-1"),
            version_id=MediaVersionId("lesson-v1"),
        ),
    )


def _metadata(request: AuthorizedMediaVersion, *, path: str) -> MediaDeliveryMetadata:
    grant = PlaybackGrantDescriptor(
        grant_id="grant-1",
        authorization=request.authorization,
        activity_id=request.activity_id,
        activity_version=request.activity_version,
        media_version=request.media_version,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )
    return MediaDeliveryMetadata(
        authorization=request.authorization,
        activity_id=request.activity_id,
        activity_version=request.activity_version,
        media_version=request.media_version,
        grant=grant,
        delivery=MediaDeliveryDescriptor(
            kind=MediaDeliveryKind.HLS,
            url=EphemeralMediaUrl(f"https://media.example.test/{path}/master.m3u8"),
        ),
        fallback=MediaDeliveryDescriptor(
            kind=MediaDeliveryKind.PROGRESSIVE,
            url=EphemeralMediaUrl(f"https://media.example.test/{path}/lesson.mp4"),
            supports_range=True,
        ),
        poster=PosterDescriptor(
            url=EphemeralMediaUrl(f"https://media.example.test/{path}/poster.jpg"),
            width=1600,
            height=900,
            mime_type="image/jpeg",
        ),
        captions=(
            CaptionTrackDescriptor(
                language="en",
                label="English",
                url=EphemeralMediaUrl(f"https://media.example.test/{path}/captions.vtt"),
                is_default=True,
            ),
        ),
        transcript=TranscriptDescriptor(
            language="en",
            format=TranscriptFormat.WEBVTT,
            url=EphemeralMediaUrl(f"https://media.example.test/{path}/transcript.vtt"),
        ),
        duration_seconds=600,
        renditions=(
            RenditionDescriptor(
                name="1080p",
                width=1920,
                height=1080,
                bitrate_kbps=5000,
                mime_type="video/mp4",
            ),
        ),
    )


class _FakeVpsAdapter:
    async def resolve_delivery(
        self,
        request: AuthorizedMediaVersion,
    ) -> MediaDeliveryMetadata:
        return _metadata(request, path="vps")


class _FakeCdnAdapter:
    async def resolve_delivery(
        self,
        request: AuthorizedMediaVersion,
    ) -> MediaDeliveryMetadata:
        return _metadata(request, path="cdn")


class _MismatchedAdapter:
    async def resolve_delivery(
        self,
        request: AuthorizedMediaVersion,
    ) -> MediaDeliveryMetadata:
        del request
        return _metadata(_request(activity_id="other-activity"), path="other-scope")


def test_authorization_context_is_factory_created_and_scope_bound() -> None:
    other = create_media_authorization_context(
        tenant_id="tenant-1",
        person_id="person-1",
        session_id="session-2",
    )
    assert other != AUTHORIZATION
    assert repr(AUTHORIZATION) == "MediaAuthorizationContext()"
    with pytest.raises(TypeError, match="server factory"):
        MediaAuthorizationContext(
            _binding=("tenant-1", "person-1", "session-1"),
            _seal=object(),
        )


def test_media_identifiers_are_immutable_and_provider_opaque() -> None:
    asset_id = MediaAssetId(" asset-1 ")
    version_id = MediaVersionId("version-1")

    assert asset_id.value == "asset-1"
    assert version_id.value == "version-1"
    with pytest.raises(FrozenInstanceError):
        asset_id.value = "other"  # type: ignore[misc]
    with pytest.raises(ValueError):
        MediaAssetId("https://provider.example/asset")


def test_nested_values_are_validated_or_coerced_at_runtime() -> None:
    asset = MediaAssetVersion(
        cast(MediaAssetId, "asset-raw"),
        cast(MediaVersionId, "version-raw"),
    )
    assert isinstance(asset.asset_id, MediaAssetId)
    assert isinstance(asset.version_id, MediaVersionId)

    delivery = MediaDeliveryDescriptor(
        kind=MediaDeliveryKind.HLS,
        url=cast(EphemeralMediaUrl, "https://media.example.test/master.m3u8"),
    )
    assert isinstance(delivery.url, EphemeralMediaUrl)
    with pytest.raises(ValueError):
        MediaDeliveryDescriptor(
            kind=MediaDeliveryKind.HLS,
            url=cast(EphemeralMediaUrl, "http://media.example.test/master.m3u8"),
        )

    poster = PosterDescriptor(
        url=cast(EphemeralMediaUrl, "https://media.example.test/poster.jpg"),
        width=1,
        height=1,
        mime_type="image/jpeg",
    )
    caption = CaptionTrackDescriptor(
        language="en",
        label="English",
        url=cast(EphemeralMediaUrl, "https://media.example.test/captions.vtt"),
    )
    transcript = TranscriptDescriptor(
        language="en",
        format=TranscriptFormat.WEBVTT,
        url=cast(EphemeralMediaUrl, "https://media.example.test/transcript.vtt"),
    )
    assert isinstance(poster.url, EphemeralMediaUrl)
    assert isinstance(caption.url, EphemeralMediaUrl)
    assert isinstance(transcript.url, EphemeralMediaUrl)

    metadata = _metadata(_request(), path="vps")
    with pytest.raises(TypeError, match="captions"):
        MediaDeliveryMetadata(
            authorization=metadata.authorization,
            activity_id=metadata.activity_id,
            activity_version=metadata.activity_version,
            media_version=metadata.media_version,
            grant=metadata.grant,
            delivery=metadata.delivery,
            captions=(cast(CaptionTrackDescriptor, "not-a-caption"),),
        )
    with pytest.raises(TypeError, match="renditions"):
        MediaDeliveryMetadata(
            authorization=metadata.authorization,
            activity_id=metadata.activity_id,
            activity_version=metadata.activity_version,
            media_version=metadata.media_version,
            grant=metadata.grant,
            delivery=metadata.delivery,
            renditions=(cast(RenditionDescriptor, "not-a-rendition"),),
        )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: MediaAssetId(""),
        lambda: MediaVersionId("asset/version"),
        lambda: EphemeralMediaUrl("http://media.example.test/lesson.mp4"),
        lambda: EphemeralMediaUrl("https://user:password@media.example.test/lesson.mp4"),
        lambda: EphemeralMediaUrl("https://media.example.test/lesson.mp4#fragment"),
        lambda: EphemeralMediaUrl("https://media.example.test/lesson.mp4#"),
        lambda: EphemeralMediaUrl("https://media.example.test/lesson with space.mp4"),
        lambda: EphemeralMediaUrl("https://media.example.test:99999/lesson.mp4"),
        lambda: EphemeralMediaUrl(f"https://media.example.test/lesson{chr(0)}.mp4"),
        lambda: EphemeralMediaUrl(f"https://media.example.test/lesson{chr(9)}.mp4"),
        lambda: EphemeralMediaUrl(f"https://media.example.test/lesson{chr(127)}.mp4"),
    ],
)
def test_contract_rejects_unsafe_or_unbounded_values(factory: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        factory()  # type: ignore[operator]


def test_descriptors_validate_dimensions_mime_and_caption_defaults() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        PosterDescriptor(
            url=EphemeralMediaUrl("https://media.example.test/poster.jpg"),
            width=0,
            height=900,
            mime_type="image/jpeg",
        )
    with pytest.raises(ValueError, match="MIME"):
        RenditionDescriptor(
            name="1080p",
            width=1920,
            height=1080,
            bitrate_kbps=5000,
            mime_type="video",
        )
    with pytest.raises(ValueError, match="at most one"):
        metadata = _metadata(_request(), path="vps")
        MediaDeliveryMetadata(
            authorization=metadata.authorization,
            activity_id=metadata.activity_id,
            activity_version=metadata.activity_version,
            media_version=metadata.media_version,
            grant=metadata.grant,
            delivery=metadata.delivery,
            captions=(
                metadata.captions[0],
                CaptionTrackDescriptor(
                    language="fr",
                    label="French",
                    url=EphemeralMediaUrl("https://media.example.test/fr.vtt"),
                    is_default=True,
                ),
            ),
        )
    with pytest.raises(ValueError, match="byte ranges"):
        metadata = _metadata(_request(), path="vps")
        MediaDeliveryMetadata(
            authorization=metadata.authorization,
            activity_id=metadata.activity_id,
            activity_version=metadata.activity_version,
            media_version=metadata.media_version,
            grant=metadata.grant,
            delivery=metadata.delivery,
            fallback=MediaDeliveryDescriptor(
                kind=MediaDeliveryKind.PROGRESSIVE,
                url=EphemeralMediaUrl("https://media.example.test/fallback.mp4"),
                supports_range=False,
            ),
        )


def test_caption_language_uniqueness_is_case_insensitive() -> None:
    metadata = _metadata(_request(), path="vps")
    with pytest.raises(ValueError, match="caption languages"):
        MediaDeliveryMetadata(
            authorization=metadata.authorization,
            activity_id=metadata.activity_id,
            activity_version=metadata.activity_version,
            media_version=metadata.media_version,
            grant=metadata.grant,
            delivery=metadata.delivery,
            captions=(
                CaptionTrackDescriptor(
                    language="en",
                    label="English",
                    url=EphemeralMediaUrl("https://media.example.test/en.vtt"),
                ),
                CaptionTrackDescriptor(
                    language="EN",
                    label="English uppercase",
                    url=EphemeralMediaUrl("https://media.example.test/EN.vtt"),
                ),
            ),
        )


def test_playback_grant_requires_ordered_aware_expiry_and_expires_fail_closed() -> None:
    request = _request()
    grant = PlaybackGrantDescriptor(
        grant_id="grant-1",
        authorization=request.authorization,
        activity_id=request.activity_id,
        activity_version=request.activity_version,
        media_version=request.media_version,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )

    assert not grant.is_expired(now=NOW + timedelta(minutes=9))
    grant.validate(now=NOW + timedelta(minutes=9), max_lifetime=timedelta(minutes=15))
    with pytest.raises(MediaExpiredError):
        grant.validate(now=NOW + timedelta(minutes=10))
    future_grant = PlaybackGrantDescriptor(
        grant_id="grant-future",
        authorization=request.authorization,
        activity_id=request.activity_id,
        activity_version=request.activity_version,
        media_version=request.media_version,
        issued_at=NOW + timedelta(hours=1),
        expires_at=NOW + timedelta(hours=2),
    )
    with pytest.raises(MediaNotYetValidError):
        future_grant.validate(now=NOW)
    with pytest.raises(ValueError, match="timezone-aware"):
        PlaybackGrantDescriptor(
            grant_id="grant-2",
            authorization=request.authorization,
            activity_id=request.activity_id,
            activity_version=request.activity_version,
            media_version=request.media_version,
            issued_at=datetime(2026, 9, 2, 12),
            expires_at=NOW + timedelta(minutes=10),
        )
    with pytest.raises(ValueError, match="lifetime"):
        grant.validate(now=NOW, max_lifetime=timedelta(minutes=5))
    with pytest.raises(TypeError, match="now must be a datetime"):
        grant.is_expired(now=cast(datetime, "not-a-datetime"))


def test_metadata_binds_grant_scope_and_keeps_nested_collections_immutable() -> None:
    metadata = _metadata(_request(), path="vps")
    assert isinstance(metadata.captions, tuple)
    assert isinstance(metadata.renditions, tuple)
    with pytest.raises(ValueError, match="scope"):
        MediaDeliveryMetadata(
            authorization=metadata.authorization,
            activity_id="different-activity",
            activity_version=metadata.activity_version,
            media_version=metadata.media_version,
            grant=metadata.grant,
            delivery=metadata.delivery,
        )
    with pytest.raises(MediaAuthorizationMismatchError):
        metadata.validate_for_request(
            _request(
                authorization=create_media_authorization_context(
                    tenant_id="tenant-1",
                    person_id="person-1",
                    session_id="session-2",
                )
            ),
            now=NOW,
        )
    for mismatched_request in (
        _request(activity_id="different-activity"),
        _request(activity_version="activity-v2"),
        _request(
            media_version=MediaAssetVersion(
                asset_id=MediaAssetId("lesson-2"),
                version_id=MediaVersionId("lesson-v2"),
            )
        ),
    ):
        with pytest.raises(MediaAuthorizationMismatchError):
            metadata.validate_for_request(mismatched_request, now=NOW)


def test_typed_delivery_failures_are_distinct_and_provider_neutral() -> None:
    failures = (
        MediaUnavailableError,
        MediaProcessingError,
        MediaUnsupportedError,
        MediaRangeError,
        MediaExpiredError,
        MediaNotYetValidError,
        MediaAuthorizationMismatchError,
        MediaPolicyDeniedError,
        MediaOriginError,
    )
    assert all(issubclass(failure, RuntimeError) for failure in failures)
    assert len({failure.code for failure in failures}) == len(failures)
    assert all(not hasattr(failure("safe"), "provider") for failure in failures)


@pytest.mark.asyncio
async def test_vps_and_cdn_adapters_swap_behind_the_same_port_contract() -> None:
    request = _request()
    adapters: tuple[MediaDeliveryPort, ...] = (_FakeVpsAdapter(), _FakeCdnAdapter())

    assert all(isinstance(adapter, MediaDeliveryPort) for adapter in adapters)
    results = [await resolve_authorized_delivery(adapter, request, now=NOW) for adapter in adapters]

    assert all(result.media_version == request.media_version for result in results)
    assert all(result.activity_id == request.activity_id for result in results)
    assert all(result.delivery.kind is MediaDeliveryKind.HLS for result in results)
    assert all(result.fallback is not None and result.fallback.supports_range for result in results)
    assert type(results[0]) is type(results[1]) is MediaDeliveryMetadata
    assert "provider" not in {field.name for field in fields(MediaDeliveryMetadata)}
    assert "provider_reference" not in {field.name for field in fields(MediaDeliveryMetadata)}
    assert "/vps/" in str(results[0].delivery.url)
    assert "/cdn/" in str(results[1].delivery.url)


@pytest.mark.asyncio
async def test_authorized_resolution_rejects_mismatched_adapter_output() -> None:
    with pytest.raises(MediaAuthorizationMismatchError):
        await resolve_authorized_delivery(_MismatchedAdapter(), _request(), now=NOW)
