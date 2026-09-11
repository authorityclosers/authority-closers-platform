from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ac_platform.http.app import create_app
from ac_platform.http.media_delivery import install_media_delivery_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.media.contracts import (
    MediaAssetId,
    MediaAssetVersion,
    MediaVersionId,
    create_media_authorization_context,
)
from ac_platform.media.delivery import MediaDeliveryResult, PrivateMediaDeliveryHandler
from ac_platform.media.errors import MediaForbidden, MediaStorageUnavailable
from ac_platform.media.policy import MediaCorsPolicy, SignedMediaDeliveryPort
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import (
    InMemoryPrivateObjectStorage,
    S3CompatiblePrivateObjectStorage,
)

NOW = datetime(2026, 9, 4, 8, 0, tzinfo=UTC)
TENANT = "tenant-1"
ASSET = "asset-1"
VERSION = "version-1"
MEDIA_ROOT = f"tenants/{TENANT}/media/video/{ASSET}/{VERSION}"
PLAYBACK = "playback"
READ = "read"


@pytest.fixture
def delivery_harness() -> tuple[PrivateMediaDeliveryHandler, InMemoryPrivateObjectStorage]:
    signer = MediaSigner("media-delivery-phase2-signer-value-32-bytes!!")
    storage = InMemoryPrivateObjectStorage(signer)
    port = SignedMediaDeliveryPort(
        signer=signer,
        delivery_origin="https://media.test",
    )
    handler = PrivateMediaDeliveryHandler(
        storage=storage,
        signer=signer,
        delivery_port=port,
        cors_policy=MediaCorsPolicy(("https://app.test",)),
        authorizer=lambda _claims, _token_type: True,
        chunk_size=3,
    )
    return handler, storage


def _token(
    handler: PrivateMediaDeliveryHandler,
    object_key: str,
    *,
    kind: str = "playback",
    now: datetime = NOW,
    supports_range: bool | None = None,
) -> str:
    authorization = create_media_authorization_context(
        tenant_id=TENANT,
        person_id="person-1",
        session_id="session-1",
    )
    signed = handler.delivery_port.issue(
        authorization=authorization,
        activity_id="activity-1",
        activity_version="activity-version-1",
        media_version=MediaAssetVersion(MediaAssetId(ASSET), MediaVersionId(VERSION)),
        object_key=object_key,
        now=now,
        kind=kind,
        supports_range=kind == "playback" if supports_range is None else supports_range,
    )
    return signed.token


def _absolute_path_and_token(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    prefix = "/v1/media/playback/"
    assert parsed.path.startswith(prefix)
    object_key = unquote(parsed.path[len(prefix) :])
    token = parse_qs(parsed.query, keep_blank_values=True)["token"][0]
    return object_key, token


def test_progressive_delivery_streams_exact_object_and_emits_private_headers(
    delivery_harness: tuple[PrivateMediaDeliveryHandler, InMemoryPrivateObjectStorage],
) -> None:
    handler, storage = delivery_harness
    object_key = f"{MEDIA_ROOT}/renditions/progressive.mp4"
    body = b"0123456789"
    metadata = storage.put(object_key=object_key, body=body, content_type="video/mp4")

    result = handler.serve(
        token=_token(handler, object_key),
        token_type=PLAYBACK,
        object_key=object_key,
        origin="https://app.test",
        now=NOW + timedelta(minutes=1),
    )

    assert isinstance(result, MediaDeliveryResult)
    assert result.status_code == 200
    assert result.content_type == "video/mp4"
    assert result.content_length == len(body)
    assert b"".join(result.body or ()) == body
    assert result.headers["Content-Length"] == str(len(body))
    assert result.headers["ETag"] == f'"{metadata.checksum_sha256}"'
    assert result.headers["Cache-Control"] == "private, no-store"
    assert result.headers["Referrer-Policy"] == "no-referrer"
    assert result.headers["Access-Control-Allow-Origin"] == "https://app.test"


def test_progressive_delivery_supports_one_bounded_range_and_head(
    delivery_harness: tuple[PrivateMediaDeliveryHandler, InMemoryPrivateObjectStorage],
) -> None:
    handler, storage = delivery_harness
    object_key = f"{MEDIA_ROOT}/renditions/progressive.mp4"
    body = b"0123456789"
    storage.put(object_key=object_key, body=body, content_type="video/mp4")
    token = _token(handler, object_key)

    ranged = handler.serve(
        token=token,
        token_type=PLAYBACK,
        object_key=object_key,
        origin="https://app.test",
        range_header="bytes=2-5",
        now=NOW + timedelta(minutes=1),
    )
    assert ranged.status_code == 206
    assert ranged.content_length == 4
    assert ranged.headers["Content-Range"] == "bytes 2-5/10"
    assert b"".join(ranged.body or ()) == b"2345"

    head = handler.serve(
        token=token,
        token_type=PLAYBACK,
        object_key=object_key,
        method="HEAD",
        origin="https://app.test",
        now=NOW + timedelta(minutes=1),
    )
    assert head.status_code == 200
    assert head.content_length == len(body)
    assert head.body is None


def test_s3_compatible_range_adapter_is_a_bounded_streaming_contract() -> None:
    class FakeBody:
        def __init__(self) -> None:
            self.data = b"0123456789"
            # The provider is expected to honor the requested Range before
            # returning this body stream.
            self.offset = 2
            self.read_sizes: list[int] = []
            self.closed = False

        def read(self, size: int) -> bytes:
            self.read_sizes.append(size)
            chunk = self.data[self.offset : self.offset + size]
            self.offset += len(chunk)
            return chunk

        def close(self) -> None:
            self.closed = True

    class FakeClient:
        def __init__(self, body: FakeBody) -> None:
            self.body = body
            self.kwargs: dict[str, object] | None = None

        def get_object(self, **kwargs: object) -> dict[str, object]:
            self.kwargs = kwargs
            return {"Body": self.body}

    body = FakeBody()
    client = FakeClient(body)
    adapter = object.__new__(S3CompatiblePrivateObjectStorage)
    adapter._client = client
    adapter._bucket = "ac-media"
    adapter._endpoint_url = None
    adapter._endpoint_addresses = ()

    chunks = tuple(
        adapter.iter_range("tenants/t/media/video/a/v/segment.ts", start=2, end=7, chunk_size=2)
    )

    assert chunks == (b"23", b"45", b"67")
    assert client.kwargs == {
        "Bucket": "ac-media",
        "Key": "tenants/t/media/video/a/v/segment.ts",
        "Range": "bytes=2-7",
    }
    assert body.read_sizes == [2, 2, 2]
    assert body.closed is True


class _AdversarialStorage(InMemoryPrivateObjectStorage):
    def __init__(self, signer: MediaSigner, behavior: str) -> None:
        super().__init__(signer)
        self.behavior = behavior

    def iter_range(
        self,
        object_key: str,
        *,
        start: int = 0,
        end: int | None = None,
        chunk_size: int = 1024 * 1024,
    ):
        if self.behavior == "oversized":
            yield b"0123456789"
            return
        if self.behavior == "undersized":
            yield b"012"
            return
        if self.behavior == "mutated-bytes":
            self.put(
                object_key=object_key,
                body=b"abcdefghij",
                content_type="video/mp4",
                storage_version_id="mutated-version",
            )
            yield from super().iter_range(object_key, start=start, end=end, chunk_size=chunk_size)
            return
        if self.behavior == "mutated-version":
            original = self.read(object_key)
            self.put(
                object_key=object_key,
                body=original,
                content_type="video/mp4",
                storage_version_id="mutated-version",
            )
            yield from super().iter_range(object_key, start=start, end=end, chunk_size=chunk_size)
            return
        yield from super().iter_range(object_key, start=start, end=end, chunk_size=chunk_size)


@pytest.mark.parametrize(
    "behavior", ["oversized", "undersized", "mutated-bytes", "mutated-version"]
)
@pytest.mark.parametrize("range_header", [None, "bytes=2-5"], ids=["full", "range"])
def test_delivery_rejects_adversarial_stream_integrity(
    behavior: str,
    range_header: str | None,
    delivery_harness: tuple[PrivateMediaDeliveryHandler, InMemoryPrivateObjectStorage],
) -> None:
    handler, _ = delivery_harness
    storage = _AdversarialStorage(handler.signer, behavior)
    handler.storage = storage
    object_key = f"{MEDIA_ROOT}/renditions/progressive.mp4"
    storage.put(
        object_key=object_key,
        body=b"0123456789",
        content_type="video/mp4",
        storage_version_id="original-version",
    )
    result = handler.serve(
        token=_token(handler, object_key),
        token_type=PLAYBACK,
        object_key=object_key,
        range_header=range_header,
        now=NOW + timedelta(minutes=1),
    )

    with pytest.raises(MediaStorageUnavailable):
        b"".join(result.body or ())


def test_delivery_enforces_per_url_range_policy_for_captions_and_progressive_urls(
    delivery_harness: tuple[PrivateMediaDeliveryHandler, InMemoryPrivateObjectStorage],
) -> None:
    handler, storage = delivery_harness
    progressive_key = f"{MEDIA_ROOT}/renditions/progressive.mp4"
    caption_key = f"{MEDIA_ROOT}/captions/en.vtt"
    storage.put(object_key=progressive_key, body=b"0123456789", content_type="video/mp4")
    storage.put(object_key=caption_key, body=b"WEBVTT\n", content_type="text/vtt")

    progressive = handler.serve(
        token=_token(handler, progressive_key, supports_range=False),
        token_type=PLAYBACK,
        object_key=progressive_key,
        range_header="bytes=0-1",
        now=NOW + timedelta(minutes=1),
    )
    caption = handler.serve(
        token=_token(handler, caption_key, kind="read", supports_range=False),
        token_type=READ,
        object_key=caption_key,
        range_header="bytes=0-1",
        now=NOW + timedelta(minutes=1),
    )

    assert progressive.status_code == 416
    assert progressive.headers["Accept-Ranges"] == "none"
    assert caption.status_code == 416
    assert caption.headers["Accept-Ranges"] == "none"


def test_delivery_rejects_token_path_expiry_and_origin_tampering(
    delivery_harness: tuple[PrivateMediaDeliveryHandler, InMemoryPrivateObjectStorage],
) -> None:
    handler, storage = delivery_harness
    object_key = f"{MEDIA_ROOT}/renditions/progressive.mp4"
    storage.put(object_key=object_key, body=b"video", content_type="video/mp4")
    token = _token(handler, object_key)

    with pytest.raises(MediaForbidden):
        handler.serve(
            token=token,
            token_type=PLAYBACK,
            object_key=f"{MEDIA_ROOT}/renditions/other.mp4",
            now=NOW + timedelta(minutes=1),
        )
    with pytest.raises(MediaForbidden):
        handler.serve(
            token=token,
            token_type=PLAYBACK,
            object_key=object_key,
            origin="https://attacker.test",
            now=NOW + timedelta(minutes=1),
        )
    with pytest.raises(MediaForbidden):
        handler.serve(
            token=token,
            token_type=PLAYBACK,
            object_key=object_key,
            now=NOW + timedelta(minutes=16),
        )


def test_delivery_rejects_misleading_version_marker_paths(
    delivery_harness: tuple[PrivateMediaDeliveryHandler, InMemoryPrivateObjectStorage],
) -> None:
    handler, storage = delivery_harness
    misleading_key = (
        f"tenants/{TENANT}/media/video/not-the-asset/{ASSET}/{VERSION}/renditions/video.mp4"
    )
    storage.put(object_key=misleading_key, body=b"video", content_type="video/mp4")

    with pytest.raises(MediaForbidden):
        handler.serve(
            token=_token(handler, misleading_key),
            token_type=PLAYBACK,
            object_key=misleading_key,
            now=NOW + timedelta(minutes=1),
        )


@pytest.mark.parametrize(
    "rendition_root",
    [
        "renditions",
        "original/renditions",
        "original/attempts/64a14d8c-32ec-4a2b-989f-f3ed9ea9eb03/renditions",
    ],
)
def test_hls_delivery_rewrites_each_private_child_with_an_exact_child_token(
    delivery_harness: tuple[PrivateMediaDeliveryHandler, InMemoryPrivateObjectStorage],
    rendition_root: str,
) -> None:
    handler, storage = delivery_harness
    master_key = f"{MEDIA_ROOT}/{rendition_root}/master.m3u8"
    playlist_key = f"{MEDIA_ROOT}/{rendition_root}/hls/360p/index.m3u8"
    segment_key = f"{MEDIA_ROOT}/{rendition_root}/hls/360p/segment-000.ts"
    storage.put(
        object_key=master_key,
        body=b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\nhls/360p/index.m3u8\n",
        content_type="application/vnd.apple.mpegurl",
    )
    storage.put(
        object_key=playlist_key,
        body=b"#EXTM3U\n#EXTINF:1,\nsegment-000.ts\n#EXT-X-ENDLIST\n",
        content_type="application/vnd.apple.mpegurl",
    )
    storage.put(object_key=segment_key, body=b"segment", content_type="video/mp2t")

    master = handler.serve(
        token=_token(handler, master_key),
        token_type=PLAYBACK,
        object_key=master_key,
        origin="https://app.test",
        now=NOW + timedelta(minutes=1),
    )
    master_text = b"".join(master.body or ()).decode()
    assert "hls/360p/index.m3u8" not in master_text
    rewritten_playlist_key, playlist_token = _absolute_path_and_token(master_text.splitlines()[-1])
    assert rewritten_playlist_key == playlist_key

    playlist = handler.serve(
        token=playlist_token,
        token_type=PLAYBACK,
        object_key=playlist_key,
        origin="https://app.test",
        now=NOW + timedelta(minutes=1),
    )
    playlist_text = b"".join(playlist.body or ()).decode()
    assert "\nsegment-000.ts\n" not in playlist_text
    rewritten_segment_key, segment_token = _absolute_path_and_token(playlist_text.splitlines()[2])
    assert rewritten_segment_key == segment_key

    segment = handler.serve(
        token=segment_token,
        token_type=PLAYBACK,
        object_key=segment_key,
        origin="https://app.test",
        now=NOW + timedelta(minutes=1),
    )
    child_range = handler.serve(
        token=segment_token,
        token_type=PLAYBACK,
        object_key=segment_key,
        range_header="bytes=0-1",
        now=NOW + timedelta(minutes=1),
    )
    assert segment.status_code == 200
    assert b"".join(segment.body or ()) == b"segment"
    assert child_range.status_code == 416
    assert child_range.headers["Accept-Ranges"] == "none"


@pytest.mark.parametrize(
    "suffix",
    [
        "original/attempts/not-a-uuid/renditions",
        "original/attempts/00000000-0000-0000-0000-000000000000/renditions",
        "original/attempts/64A14D8C-32EC-4A2B-989F-F3ED9EA9EB03/renditions",
        "original/attempts/64a14d8c32ec4a2b989ff3ed9ea9eb03/renditions",
        "original/extra/attempts/64a14d8c-32ec-4a2b-989f-f3ed9ea9eb03/renditions",
        "original/attempts/64a14d8c-32ec-4a2b-989f-f3ed9ea9eb03/extra/renditions",
    ],
)
def test_hls_attempt_namespace_requires_exact_canonical_attempt(delivery_harness, suffix):
    handler, storage = delivery_harness
    key = f"{MEDIA_ROOT}/{suffix}/master.m3u8"
    storage.put(
        object_key=key,
        body=b"#EXTM3U\n#EXT-X-ENDLIST\n",
        content_type="application/vnd.apple.mpegurl",
    )
    with pytest.raises(MediaStorageUnavailable, match="rendition namespace"):
        handler.serve(token=_token(handler, key), token_type=PLAYBACK, object_key=key, now=NOW)


def test_hls_attempt_cannot_reference_a_different_attempt(delivery_harness):
    handler, storage = delivery_harness
    first = "64a14d8c-32ec-4a2b-989f-f3ed9ea9eb03"
    second = "3907a702-ae44-40e3-8c43-2849a587bb0a"
    key = f"{MEDIA_ROOT}/original/attempts/{first}/renditions/master.m3u8"
    sibling = f"{MEDIA_ROOT}/original/attempts/{second}/renditions/segment.ts"
    storage.put(object_key=sibling, body=b"private-sibling", content_type="video/mp2t")
    storage.put(
        object_key=key,
        body=f"#EXTM3U\n#EXTINF:1,\n../../{second}/renditions/segment.ts\n#EXT-X-ENDLIST\n".encode(),
        content_type="application/vnd.apple.mpegurl",
    )
    with pytest.raises(MediaStorageUnavailable, match="not deliverable"):
        handler.serve(token=_token(handler, key), token_type=PLAYBACK, object_key=key, now=NOW)


def test_hls_delivery_fails_closed_for_external_or_missing_children(
    delivery_harness: tuple[PrivateMediaDeliveryHandler, InMemoryPrivateObjectStorage],
) -> None:
    handler, storage = delivery_harness
    external_key = f"{MEDIA_ROOT}/renditions/external.m3u8"
    storage.put(
        object_key=external_key,
        body=b"#EXTM3U\nhttps://attacker.test/segment.ts\n",
        content_type="application/vnd.apple.mpegurl",
    )
    with pytest.raises(MediaStorageUnavailable):
        handler.serve(
            token=_token(handler, external_key),
            token_type=PLAYBACK,
            object_key=external_key,
            now=NOW + timedelta(minutes=1),
        )

    missing_key = f"{MEDIA_ROOT}/renditions/missing.m3u8"
    storage.put(
        object_key=missing_key,
        body=b"#EXTM3U\nmissing/index.m3u8\n",
        content_type="application/vnd.apple.mpegurl",
    )
    with pytest.raises(MediaStorageUnavailable):
        handler.serve(
            token=_token(handler, missing_key),
            token_type=PLAYBACK,
            object_key=missing_key,
            now=NOW + timedelta(minutes=1),
        )


def test_delivery_http_installer_serves_streams_and_preflight_without_default_mount(
    delivery_harness: tuple[PrivateMediaDeliveryHandler, InMemoryPrivateObjectStorage],
) -> None:
    handler, storage = delivery_harness
    object_key = f"{MEDIA_ROOT}/renditions/progressive.mp4"
    storage.put(object_key=object_key, body=b"012345", content_type="video/mp4")
    token = _token(handler, object_key, now=datetime.now(UTC))
    parsed = urlsplit(
        handler.delivery_port.issue(
            authorization=create_media_authorization_context(
                tenant_id=TENANT,
                person_id="person-1",
                session_id="session-1",
            ),
            activity_id="activity-1",
            activity_version="activity-version-1",
            media_version=MediaAssetVersion(MediaAssetId(ASSET), MediaVersionId(VERSION)),
            object_key=object_key,
            now=datetime.now(UTC),
            kind="playback",
            supports_range=True,
        ).url.value
    )
    application = FastAPI()
    register_problem_handlers(application)
    install_media_delivery_http(
        application,
        handler=handler,
        cors_policy=handler.cors_policy,
    )

    with TestClient(application) as client:
        response = client.get(
            parsed.path + f"?token={token}",
            headers={"Origin": "https://app.test"},
        )
        preflight = client.options(
            parsed.path,
            headers={
                "Origin": "https://app.test",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.content == b"012345"
    assert response.headers["content-type"] == "video/mp4"
    assert preflight.status_code == 204
    assert preflight.headers["access-control-allow-origin"] == "https://app.test"


def test_default_application_keeps_delivery_router_unmounted() -> None:
    paths = create_app().openapi()["paths"]

    assert "/v1/media/{kind}/{object_key}" not in paths
