from __future__ import annotations

import hashlib
import io
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from PIL import Image
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from ac_platform.application.settings import Settings
from ac_platform.db.models import model_metadata
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.media.api_contracts import CropMetadata, UploadCompleteRequest, UploadIntentRequest
from ac_platform.media.delivery import PrivateMediaDeliveryHandler
from ac_platform.media.errors import (
    MediaBadRequest,
    MediaConflict,
    MediaForbidden,
    MediaProcessingError,
    MediaStorageUnavailable,
)
from ac_platform.media.local_avatar_processing import (
    LocalAvatarProcessor,
    LocalAvatarScanner,
    decode_avatar,
)
from ac_platform.media.local_avatar_runtime import LocalAvatarMediaService, LocalAvatarRuntime
from ac_platform.media.local_avatar_storage import LOCAL_AVATAR_ORIGIN, LocalAvatarStorage
from ac_platform.media.models import (
    MediaAsset,
    MediaLifecycle,
    MediaPurpose,
    MediaUploadIntent,
    MediaVersion,
)
from ac_platform.media.policy import MediaCorsPolicy, SignedMediaDeliveryPort
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import (
    _LOCAL_AVATAR_UPLOAD_CONTRACT,
    InMemoryPrivateObjectStorage,
    StorageUploadIntent,
)
from ac_platform.tenancy.models import Membership, Tenant


def picture(format: str = "PNG", size: tuple[int, int] = (160, 80), **options: object) -> bytes:
    with Image.new("RGB", size, "red") as image:
        image.paste("blue", (size[0] // 2, 0, size[0], size[1]))
        stream = io.BytesIO()
        image.save(stream, format=format, **options)
        return stream.getvalue()


@pytest.fixture
def harness(tmp_path):
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    model_metadata().create_all(engine)
    with Session(engine) as database:
        tenant = Tenant(id=uuid4(), slug="local-photo", name="Local photo")
        person = Person(id=uuid4(), email="photo@ac.localhost")
        database.add_all([tenant, person])
        database.flush()
        database.add(Membership(tenant_id=tenant.id, person_id=person.id, role="learner"))
        database.flush()
        identity = IdentitySession(
            id=uuid4(),
            person_id=person.id,
            selected_tenant_id=tenant.id,
            token_hash=b"q" * 32,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        database.add(identity)
        database.commit()
        actor = ActorContext(
            person_id=person.id,
            session_id=identity.id,
            tenant_id=tenant.id,
            permissions=frozenset(),
        )
        signer = MediaSigner(b"local-avatar-tests-no-secrets-123456789")
        fallback = InMemoryPrivateObjectStorage(signer)
        storage = LocalAvatarStorage(
            root=tmp_path / "avatar-objects", signer=signer, fallback=fallback
        )
        port = SignedMediaDeliveryPort(
            signer=signer, delivery_origin=LOCAL_AVATAR_ORIGIN, allow_loopback_http=True
        )
        service = LocalAvatarMediaService(
            storage=storage,
            signer=signer,
            webhook_secret=b"x" * 32,
            scanner=LocalAvatarScanner(),
            processor=LocalAvatarProcessor(),
            delivery_port=port,
        )
        runtime = LocalAvatarRuntime(storage, service)
        yield database, actor, runtime, fallback
    engine.dispose()


def intent(harness, *, body=None, crop=None, content_type="image/png"):
    database, actor, runtime, _ = harness
    body = body if body is not None else picture()
    request = UploadIntentRequest(
        purpose=MediaPurpose.AVATAR,
        filename="photo.png",
        content_type=content_type,
        content_length=len(body),
        checksum_sha256=hashlib.sha256(body).hexdigest(),
        crop=crop,
    )
    result = runtime.service.create_upload_intent(
        database, actor, request, idempotency_key=str(uuid4())
    )
    return result, body


def put(harness, result, body, *, actor=None, token=None, **overrides):
    database, default_actor, runtime, _ = harness
    values = dict(
        key=result.object_key,
        token=token or parse_qs(urlsplit(result.upload_url).query)["token"][0],
        body=body,
        content_type=result.upload_headers["content-type"],
        declared_length=str(len(body)),
        checksum=hashlib.sha256(body).hexdigest(),
    )
    return runtime.accept_upload(database, actor or default_actor, **(values | overrides))


def finish(harness, result, body):
    database, actor, runtime, _ = harness
    request = UploadCompleteRequest(
        actual_bytes=len(body), checksum_sha256=hashlib.sha256(body).hexdigest()
    )
    runtime.service.complete_upload(
        database,
        actor,
        result.upload_id,
        request,
        idempotency_key="complete-" + str(result.upload_id),
        expected_purpose=MediaPurpose.AVATAR,
    )
    return runtime.finish(database, actor, result.upload_id)


def test_real_variants_crop_pixels_metadata_and_persistence(harness):
    database, actor, runtime, fallback = harness
    result, body = intent(harness, crop=CropMetadata(x=0.5, y=0, width=0.5, height=1))
    assert result.upload_url.startswith(LOCAL_AVATAR_ORIGIN + "/v1/media/local-avatar-upload/")
    put(harness, result, body)
    put(harness, result, body)  # identical PUT retry is safe
    ready = finish(harness, result, body)
    assert ready.state is MediaLifecycle.READY
    assert ready.current_version.width == ready.current_version.height == 512
    for variant in ready.current_version.avatar_variants:
        with Image.open(
            io.BytesIO(runtime.storage.read(f"{result.object_key}/avatar/{variant.size_px}"))
        ) as image:
            assert image.format == "WEBP"
            assert image.size == (variant.size_px, variant.size_px)
            red, green, blue = image.convert("RGB").getpixel(
                (variant.size_px // 2, variant.size_px // 2)
            )
            assert blue > 220 and red < 30 and green < 30
            assert (
                not image.getexif() and "icc_profile" not in image.info and "xmp" not in image.info
            )
    reopened = LocalAvatarStorage(
        root=runtime.storage.root, signer=runtime.storage.signer, fallback=fallback
    )
    assert reopened.read(result.object_key) == body
    assert runtime.service.get_profile_avatar(database, actor).avatar.delivery_url


def test_signed_read_requires_current_own_session_and_replacement_supersedes(harness):
    database, actor, runtime, _ = harness
    first, body = intent(harness)
    put(harness, first, body)
    finish(harness, first, body)
    url = runtime.service.get_profile_avatar(database, actor).avatar.delivery_url
    token = parse_qs(urlsplit(url).query)["token"][0]
    claims = runtime.service.delivery_port.signer.verify(
        token,
        now=datetime.now(UTC),
        token_type="read",  # noqa: S106 - token kind
    )
    assert runtime.authorize_read(database, actor, claims)
    assert not runtime.authorize_read(database, replace(actor, person_id=uuid4()), claims)
    assert not runtime.authorize_read(database, replace(actor, tenant_id=uuid4()), claims)
    assert not runtime.authorize_read(database, replace(actor, session_id=uuid4()), claims)
    handler = PrivateMediaDeliveryHandler(
        storage=runtime.storage,
        signer=runtime.service.delivery_port.signer,
        delivery_port=runtime.service.delivery_port,
        cors_policy=MediaCorsPolicy((LOCAL_AVATAR_ORIGIN,)),
        authorizer=lambda values, kind: (
            kind == "read" and runtime.authorize_read(database, actor, values)
        ),
    )
    response = handler.serve(
        token=token,
        token_type="read",  # noqa: S106 - token kind
        object_key=claims["key"],
        origin=LOCAL_AVATAR_ORIGIN,
    )
    with Image.open(io.BytesIO(b"".join(response.body))) as decoded:
        assert decoded.size == (512, 512)
    second, replacement_body = intent(harness, body=picture(size=(100, 100)))
    assert runtime.authorize_read(database, actor, claims)  # old current preserved while pending
    put(harness, second, replacement_body)
    finish(harness, second, replacement_body)
    assert not runtime.authorize_read(database, actor, claims)
    assert database.get(MediaVersion, first.media_version_id) is not None
    assert (
        database.get(MediaVersion, second.media_version_id).supersedes_version_id
        == first.media_version_id
    )


@pytest.mark.parametrize(
    "change",
    [
        "actor",
        "session",
        "tenant",
        "expired",
        "completed",
        "revoked",
        "retired",
        "checksum",
        "mime",
        "length",
        "token",
        "key",
    ],
)
def test_upload_denials_preserve_no_bytes(harness, change):
    database, actor, runtime, _ = harness
    result, body = intent(harness)
    overrides = {}
    if change in {"actor", "session", "tenant"}:
        overrides["actor"] = replace(
            actor,
            **{
                {"actor": "person_id", "session": "session_id", "tenant": "tenant_id"}[
                    change
                ]: uuid4()
            },
        )
    elif change == "expired":
        database.get(MediaUploadIntent, result.upload_id).expires_at = datetime.now(
            UTC
        ) - timedelta(seconds=1)
    elif change == "completed":
        database.get(MediaUploadIntent, result.upload_id).state = "processing"
    elif change == "revoked":
        database.get(IdentitySession, actor.session_id).revoked_at = datetime.now(UTC)
    elif change == "retired":
        database.get(MediaAsset, result.media_id).state = "retired"
    else:
        overrides.update(
            {"checksum": "0" * 64}
            if change == "checksum"
            else {"content_type": "image/jpeg"}
            if change == "mime"
            else {"declared_length": "1"}
            if change == "length"
            else {"token": "invalid"}
            if change == "token"
            else {"key": result.object_key + "/avatar/512"}
        )
    with pytest.raises((MediaForbidden, MediaBadRequest)):
        put(harness, result, body, **overrides)
    assert runtime.storage.head(result.object_key) is None


@pytest.mark.parametrize(
    "body,content_type",
    [(b"not an image", "image/png"), (b"\x89PNG\r\n\x1a\n", "image/png"), (b"<svg/>", "image/png")],
)
def test_bad_decode_never_publishes(harness, body, content_type):
    database, actor, runtime, _ = harness
    result, body = intent(harness, body=body, content_type=content_type)
    put(harness, result, body)
    finish(harness, result, body)
    assert database.get(MediaVersion, result.media_version_id).state == "failed"
    assert runtime.service.get_profile_avatar(database, actor).avatar is None


@pytest.mark.parametrize(
    "format,mime", [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")]
)
def test_real_supported_formats(format, mime):
    with decode_avatar(picture(format=format), mime) as decoded:
        assert decoded.size == (160, 80)


def test_exif_orientation_before_crop_and_metadata_removed():
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "private original metadata"
    with decode_avatar(picture(format="JPEG", exif=exif), "image/jpeg") as decoded:
        assert decoded.size == (80, 160)
        assert not decoded.info and not decoded.getexif()


def test_oversized_dimensions_and_mime_spoof_rejected(monkeypatch):
    import ac_platform.media.local_avatar_processing as processor

    monkeypatch.setattr(processor, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(MediaProcessingError):
        decode_avatar(picture(), "image/png")
    with pytest.raises(MediaProcessingError):
        decode_avatar(picture(size=(5, 5)), "image/jpeg")


def test_animation_rejected():
    stream = io.BytesIO()
    with Image.new("RGB", (10, 10), "red") as first, Image.new("RGB", (10, 10), "blue") as second:
        first.save(stream, format="WEBP", save_all=True, append_images=[second], duration=100)
    with pytest.raises(MediaProcessingError):
        decode_avatar(stream.getvalue(), "image/webp")


def test_existing_object_is_immutable_and_corruption_is_detected(harness):
    _, _, runtime, _ = harness
    result, body = intent(harness)
    put(harness, result, body)
    with pytest.raises(MediaConflict):
        runtime.storage.put(
            object_key=result.object_key, body=body + b"x", content_type="image/png"
        )
    path = runtime.storage._path(result.object_key)
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(MediaStorageUnavailable):
        runtime.storage.read(result.object_key)


@pytest.mark.parametrize(
    "key", ["../escape", "/absolute", "tenants/../../original", "tenants/not-an-avatar", "x\\evil"]
)
def test_storage_write_namespace_denied(harness, key):
    with pytest.raises(MediaStorageUnavailable):
        harness[2].storage.put(object_key=key, body=b"image", content_type="image/png")


def test_unmarked_store_is_not_adopted(tmp_path):
    root = tmp_path / "avatar-objects"
    root.mkdir()
    (root / "existing.txt").write_text("preserve")
    signer = MediaSigner(b"x" * 32)
    with pytest.raises(MediaStorageUnavailable):
        LocalAvatarStorage(root=root, signer=signer, fallback=InMemoryPrivateObjectStorage(signer))
    assert (root / "existing.txt").read_text() == "preserve"


@pytest.mark.parametrize("environment", ["test", "staging", "production", "development"])
def test_avatar_optin_rejects_nonlocal_settings(environment):
    with pytest.raises(ValidationError):
        Settings(
            environment=environment,
            media_local_avatar_enabled=True,
            media_local_avatar_storage_root="ignored",
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://other.localhost:3100/v1/media/local-avatar-upload/key?token=x",
        "https://external.test/v1/media/local-avatar-upload/key?token=x",
        "http://learner.localhost:3100/elsewhere?token=x",
    ],
)
def test_private_local_upload_contract_cannot_widen_origin(url):
    with pytest.raises(MediaStorageUnavailable):
        StorageUploadIntent(
            url,
            "key",
            datetime.now(UTC) + timedelta(minutes=1),
            {"content-type": "image/png", "content-length": "1"},
            _contract=_LOCAL_AVATAR_UPLOAD_CONTRACT,
        )


@pytest.mark.parametrize(
    "enabled,path,expected",
    [
        (False, "/v1/media/local-avatar-upload/key", 413),
        (True, "/v1/media/local-avatar-upload/key", 204),
        (True, "/v1/profile/avatar", 413),
    ],
)
async def test_large_upload_body_limit_is_optin_and_route_specific(enabled, path, expected):
    from ac_platform.http.request_limits import RequestBodyLimitMiddleware

    sent = []

    async def receive():
        return {"type": "http.request", "body": b"x" * (1024 * 1024 + 1), "more_body": False}

    async def send(message):
        sent.append(message)

    async def app(scope, replay, output):
        received = await replay()
        assert len(received["body"]) == 1024 * 1024 + 1
        await output({"type": "http.response.start", "status": 204, "headers": []})

    middleware = RequestBodyLimitMiddleware(app, local_avatar_upload_enabled=enabled)
    await middleware({"type": "http", "method": "PUT", "path": path, "headers": []}, receive, send)
    assert sent[0]["status"] == expected


def test_normal_settings_remain_unconfigured():
    from ac_platform.media.runtime import create_default_media_runtime

    settings = Settings()
    assert settings.media_local_avatar_enabled is False
    runtime = create_default_media_runtime(settings)
    assert runtime.local_avatar_runtime is None
