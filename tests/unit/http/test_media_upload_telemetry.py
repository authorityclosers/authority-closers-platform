"""HTTP upload observations must not reject valid canonical lifecycle states."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import ac_platform.http.media as media_http
from ac_platform.application.settings import Settings
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.kernel.authz import ActorContext
from ac_platform.media.api_contracts import MediaAssetResponse, UploadIntentResponse
from ac_platform.media.models import MediaLifecycle, MediaPurpose
from ac_platform.media.runtime import MediaRuntime
from ac_platform.telemetry import InMemoryTelemetrySink, TelemetryEvent, TelemetryRecorder


@pytest.mark.parametrize("path", ["/v1/media/uploads", "/v1/profile/avatar"])
@pytest.mark.parametrize("lifecycle", ["uploading", "processing", "failed"])
def test_upload_routes_preserve_lifecycle_and_emit_bounded_outcome(monkeypatch, path, lifecycle):
    # Authentication/service/audit are explicit doubles here. The real HTTP
    # serializers and telemetry validator reproduce the former upload 500.
    actor = ActorContext(person_id=uuid4(), tenant_id=uuid4(), session_id=uuid4())
    now = datetime.now(UTC)
    asset_id, version_id, upload_id = uuid4(), uuid4(), uuid4()
    state = MediaLifecycle(lifecycle)
    created = UploadIntentResponse(
        upload_id=upload_id,
        media_id=asset_id,
        media_version_id=version_id,
        version_number=1,
        state=state,
        object_key="synthetic-private-key",
        upload_url="https://synthetic.test/upload",
        upload_headers={},
        expires_at=now + timedelta(minutes=5),
        max_bytes=1024,
    )
    completed = MediaAssetResponse(
        id=asset_id,
        tenant_id=actor.tenant_id,
        owner_person_id=actor.person_id,
        purpose=MediaPurpose.AVATAR,
        state=state,
        current_version_id=None,
        current_version=None,
        version_count=1,
        created_at=now,
        updated_at=now,
    )

    class Database:
        async def run_sync(self, callback):
            return callback(None)

    async def require_actor(_request: Request):
        yield AuthenticatedTransaction(
            database=Database(),
            identity=SimpleNamespace(),
            resolved=SimpleNamespace(actor=actor),
            token="synthetic-test-only",  # noqa: S106
        )

    audits = []

    class Audit:
        def __init__(self, _database):
            pass

        async def append_for_actor(self, _actor, **values):
            audits.append(values)

    monkeypatch.setattr(media_http, "AuditRepository", Audit)
    sink = InMemoryTelemetrySink()
    runtime = MediaRuntime(
        service=SimpleNamespace(
            create_upload_intent=lambda *args, **kwargs: created,
            complete_upload=lambda *args, **kwargs: completed,
        ),
        telemetry=TelemetryRecorder(sink),
    )
    application = FastAPI()
    media_http.install_media_http(
        application,
        settings=Settings(environment="test", public_app_url="https://app.test"),
        sessions=None,
        require_actor=require_actor,
        runtime=runtime,
    )
    creating = lifecycle == "uploading"
    body = (
        {
            "purpose": "avatar",
            "filename": "photo.png",
            "content_type": "image/png",
            "content_length": 1,
        }
        if creating
        else {"actual_bytes": 1}
    )
    target = path if creating else f"{path}/{upload_id}/complete"
    with TestClient(application) as client:
        response = client.post(
            target,
            json=body,
            headers={"origin": "https://app.test", "idempotency-key": "synthetic-command"},
        )
    assert response.status_code == (201 if creating else 200)
    assert response.json()["state"] == lifecycle
    assert response.headers["cache-control"] == "no-store"
    assert audits[-1]["payload"] == {"status": lifecycle}
    assert len(sink.events) == 1
    assert sink.events[0].name == ("media.upload.created" if creating else "media.upload.completed")
    assert dict(sink.events[0].attributes) == {"outcome": "succeeded"}


@pytest.mark.parametrize("lifecycle", ["uploading", "failed"])
def test_upload_fix_does_not_expand_shared_telemetry_status_vocabulary(lifecycle):
    with pytest.raises(ValueError):
        TelemetryEvent("media.upload.created", attributes={"status": lifecycle})


def test_filesystem_avatar_routes_keep_video_service_isolated(monkeypatch, tmp_path):
    """The HTTP routes dispatch video and avatar commands to separate services."""

    actor = ActorContext(person_id=uuid4(), tenant_id=uuid4(), session_id=uuid4())
    now = datetime.now(UTC)
    video_asset_id, video_version_id, video_upload_id = uuid4(), uuid4(), uuid4()
    avatar_asset_id, avatar_version_id, avatar_upload_id = uuid4(), uuid4(), uuid4()

    def intent_response(
        *, asset_id, version_id, upload_id, purpose: MediaPurpose
    ) -> UploadIntentResponse:
        return UploadIntentResponse(
            upload_id=upload_id,
            media_id=asset_id,
            media_version_id=version_id,
            version_number=1,
            state=MediaLifecycle.UPLOADING,
            object_key=f"synthetic-{purpose.value}-key",
            upload_url="https://synthetic.test/upload",
            upload_headers={},
            expires_at=now + timedelta(minutes=5),
            max_bytes=1024,
        )

    def asset_response(*, asset_id, purpose: MediaPurpose) -> MediaAssetResponse:
        return MediaAssetResponse(
            id=asset_id,
            tenant_id=actor.tenant_id,
            owner_person_id=actor.person_id,
            purpose=purpose,
            state=MediaLifecycle.READY,
            current_version_id=None,
            current_version=None,
            version_count=1,
            created_at=now,
            updated_at=now,
        )

    video_intent = intent_response(
        asset_id=video_asset_id,
        version_id=video_version_id,
        upload_id=video_upload_id,
        purpose=MediaPurpose.VIDEO,
    )
    avatar_intent = intent_response(
        asset_id=avatar_asset_id,
        version_id=avatar_version_id,
        upload_id=avatar_upload_id,
        purpose=MediaPurpose.AVATAR,
    )
    video_completed = asset_response(asset_id=video_asset_id, purpose=MediaPurpose.VIDEO)
    avatar_completed = asset_response(asset_id=avatar_asset_id, purpose=MediaPurpose.AVATAR)

    class RecordingService:
        def __init__(self, intent, completed):
            self.intent = intent
            self.completed = completed
            self.calls = []

        def create_upload_intent(self, database, actor_value, request, *, idempotency_key):
            self.calls.append(("create", request.purpose, idempotency_key))
            return self.intent

        def complete_upload(
            self,
            database,
            actor_value,
            upload_id,
            request,
            *,
            idempotency_key,
            expected_purpose,
        ):
            self.calls.append(("complete", upload_id, expected_purpose, idempotency_key))
            return self.completed

    video_service = RecordingService(video_intent, video_completed)
    avatar_service = RecordingService(avatar_intent, avatar_completed)

    class AvatarRuntime:
        service = avatar_service
        storage = SimpleNamespace(origin="https://app.test")

        def finish(self, database, actor_value, upload_id):
            self.finished = upload_id
            return avatar_completed

    class Database:
        async def run_sync(self, callback):
            return callback(None)

    async def require_actor(_request: Request):
        yield AuthenticatedTransaction(
            database=Database(),
            identity=SimpleNamespace(),
            resolved=SimpleNamespace(actor=actor),
            token="synthetic-test-only",  # noqa: S106
        )

    class Audit:
        def __init__(self, _database):
            pass

        async def append_for_actor(self, _actor, **values):
            del values

    monkeypatch.setattr(media_http, "AuditRepository", Audit)
    settings = Settings(
        environment="test",
        public_app_url="https://app.test",
        media_filesystem_enabled=True,
        media_filesystem_root=str(tmp_path / "video-objects"),
        media_filesystem_avatar_root=str(tmp_path / "avatar-objects"),
        media_scanner_unix_socket="/run/ac-media-safety/clamd.sock",
        media_max_upload_bytes=2_000_000_000,
    )
    runtime = SimpleNamespace(
        service=video_service,
        filesystem_avatar_runtime=AvatarRuntime(),
        local_avatar_runtime=None,
        telemetry=TelemetryRecorder(InMemoryTelemetrySink()),
    )
    application = FastAPI()
    media_http.install_media_http(
        application,
        settings=settings,
        sessions=None,
        require_actor=require_actor,
        runtime=runtime,
    )

    headers = {"origin": "https://app.test", "idempotency-key": "synthetic-command"}
    with TestClient(application) as client:
        video_create = client.post(
            "/v1/media/uploads",
            json={
                "purpose": "video",
                "filename": "lesson.mp4",
                "content_type": "video/mp4",
                "content_length": 1,
            },
            headers=headers,
        )
        avatar_create = client.post(
            "/v1/profile/avatar",
            json={
                "purpose": "avatar",
                "filename": "photo.png",
                "content_type": "image/png",
                "content_length": 1,
            },
            headers=headers,
        )
        video_complete = client.post(
            f"/v1/media/uploads/{video_upload_id}/complete",
            json={"actual_bytes": 1},
            headers=headers,
        )
        avatar_complete = client.post(
            f"/v1/profile/avatar/{avatar_upload_id}/complete",
            json={"actual_bytes": 1},
            headers=headers,
        )

    assert video_create.status_code == 201
    assert avatar_create.status_code == 201
    assert video_complete.status_code == 200
    assert avatar_complete.status_code == 200
    assert video_service.calls == [
        ("create", MediaPurpose.VIDEO, "synthetic-command"),
        ("complete", video_upload_id, None, "synthetic-command"),
    ]
    assert avatar_service.calls == [
        ("create", MediaPurpose.AVATAR, "synthetic-command"),
        ("complete", avatar_upload_id, MediaPurpose.AVATAR, "synthetic-command"),
    ]
