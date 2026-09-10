"""HTTP create -> private bytes -> scan/queue proof on a disposable real DB.

Uses the real same-host issuer, filesystem and canonical completion service.
The explicit local signature scanner validates a synthetic MP4 header/hash;
it is not a production antivirus service or proof of playable video/READY.
"""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.audit.models import AuditEvent
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.request_limits import RequestBodyLimitMiddleware
from ac_platform.http.studio_media import install_studio_media_http
from ac_platform.http.studio_video_bytes import StudioVideoByteTransport
from ac_platform.http.surfaces import CoachSurfaceMiddleware
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.media.models import MediaAsset, MediaUploadIntent, MediaVersion
from ac_platform.media.scanner import ScanResult, SignatureContentScanner
from ac_platform.media.service import MediaService
from ac_platform.media.signing import MediaSigner
from ac_platform.media.studio_video_completion import StudioVideoCompletion
from ac_platform.media.video_file_storage import VideoFileStorage
from ac_platform.outbox.models import Job
from ac_platform.worker import build_default_dispatcher
from tests.integration.test_media_delivery_renewal_postgresql import (
    _run_async,
    postgres_harness,  # noqa: F401 - isolated migrated schema, never operational edits
)
from tests.integration.test_studio_draft_authoring_postgresql import seed
from tests.integration.test_studio_video_bytes_postgresql import (
    SESSION_PEPPER,
    _resolver,
    _settings,
)

DATA = b"\x00\x00\x00\x18ftypmp42" + b"synthetic-http-video" * 400


@pytest.mark.parametrize("surface", ["coach", "admin"])
def test_real_same_host_upload_http_sequence_queues_once_without_publishing(
    postgres_harness: Any,  # noqa: F811 - imported disposable DB fixture
    tmp_path: Path,
    surface: str,
) -> None:
    async def run() -> None:
        engine = create_async_engine(postgres_harness.schema_url, pool_size=3, max_overflow=0)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            state = await seed(sessions)
            settings = _settings()
            token = f"pipeline-synthetic-session-{uuid4().hex}"
            async with sessions() as database, database.begin():
                identity = await database.get(IdentitySession, state.actors[0].session_id)
                person = await database.get(Person, state.actors[0].person_id)
                assert identity is not None and person is not None
                person.email = f"pipeline-{person.id.hex}@example.test"
                identity.token_hash = hmac.new(
                    SESSION_PEPPER.encode(), token.encode(), hashlib.sha256
                ).digest()

            storage = VideoFileStorage(
                root=tmp_path / "video-objects",
                max_object_bytes=1024 * 1024,
                max_store_bytes=8 * 1024 * 1024,
            )
            counters = {"opened": 0, "closed": 0}

            class ObservedSignatureScanner:
                calls = 0

                def scan(self, **kwargs: Any) -> ScanResult:
                    assert counters["opened"] == counters["closed"]
                    self.calls += 1
                    return SignatureContentScanner().scan(**kwargs)

            scanner = ObservedSignatureScanner()
            service = MediaService(
                storage=storage,
                signer=MediaSigner("pipeline-synthetic-media-signing-key-long-enough"),
                scanner=scanner,
                webhook_secret="pipeline-synthetic-webhook-key-long-enough",  # noqa: S106
            )
            resolver = _resolver(sessions, settings, counters, token)
            app = FastAPI()
            register_problem_handlers(app)
            install_studio_media_http(
                app,
                settings=settings,
                require_actor=resolver,
                service=service,
                byte_transport=StudioVideoByteTransport(
                    storage=storage, require_actor=resolver, settings=settings
                ),
                video_completion=StudioVideoCompletion(sessions, service, storage),
            )
            app.add_middleware(
                RequestBodyLimitMiddleware, studio_video_upload_max_bytes=storage.max_object_bytes
            )
            app.add_middleware(CoachSurfaceMiddleware, settings=settings)
            origin = str(
                settings.coach_app_url if surface == "coach" else settings.admin_app_url
            ).rstrip("/")
            path = f"/v1/admin/studio/programs/{state.program_id}/video-uploads"
            checksum = hashlib.sha256(DATA).hexdigest()
            body = {
                "filename": "Synthetic integration lecture.mp4",
                "content_type": "video/mp4",
                "content_length": len(DATA),
                "checksum_sha256": checksum,
            }
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url=origin,
                cookies={settings.session_cookie_name: token},
                headers={"origin": origin},
            ) as client:
                create = await client.post(path, json=body, headers={"idempotency-key": "admit"})
                assert create.status_code == 200, create.text
                upload = create.json()
                upload_path = f"{path}/{upload['upload_id']}"
                assert upload["upload_url"] == f"{upload_path}/bytes"
                replay = await client.post(path, json=body, headers={"idempotency-key": "admit"})
                assert replay.status_code == 200 and replay.json() == upload

                sent = await client.put(
                    upload["upload_url"], headers=upload["upload_headers"], content=DATA
                )
                assert sent.status_code == 204
                assert sent.headers["x-ac-upload-bytes"] == str(len(DATA))
                assert sent.headers["x-ac-upload-sha256"] == checksum
                before_complete = await client.get(upload_path)
                assert before_complete.status_code == 200
                assert before_complete.json()["state"] == "uploading"
                assert before_complete.json()["uploaded_bytes"] is None

                complete = await client.post(
                    f"{upload_path}/complete", headers={"idempotency-key": "complete"}
                )
                assert complete.status_code == 202, complete.text
                receipt = complete.json()
                assert receipt["state"] == "processing" and receipt["replayed"] is False
                again = await client.post(
                    f"{upload_path}/complete", headers={"idempotency-key": "complete"}
                )
                assert again.status_code == 202
                assert again.json()["processing_job_id"] == receipt["processing_job_id"]
                assert again.json()["replayed"] is True
                status = await client.get(upload_path)
                assert status.status_code == 200 and status.json()["state"] == "processing"
                assert status.json()["uploaded_bytes"] == len(DATA)
                denied_write = await client.put(
                    upload["upload_url"], headers=upload["upload_headers"], content=DATA
                )
                assert denied_write.status_code == 409

            assert scanner.calls == 1
            assert counters["opened"] == counters["closed"]
            async with sessions() as database:
                intent = await database.get(MediaUploadIntent, UUID(upload["upload_id"]))
                asset = await database.get(MediaAsset, UUID(upload["media_id"]))
                version = await database.get(MediaVersion, UUID(upload["media_version_id"]))
                assert intent is not None and asset is not None and version is not None
                assert intent.state == version.state == asset.state == "processing"
                assert asset.current_version_id is None and version.duration_seconds is None
                assert storage.read(version.object_key) == DATA
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(Job)
                        .where(
                            Job.kind == "media.process_version.v1",
                            Job.tenant_id == asset.tenant_id,
                            Job.dedupe_key
                            == f"media.process_version.v1:{asset.tenant_id}:{version.id}",
                        )
                    )
                    == 1
                )
                job = await database.get(Job, UUID(receipt["processing_job_id"]))
                assert job is not None and job.kind == "media.process_version.v1"
                assert job.status == "queued" and job.external_side_effect is False
                assert job.kind not in build_default_dispatcher().allowed_kinds
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(
                            AuditEvent.tenant_id == asset.tenant_id,
                            AuditEvent.action == "media.studio_upload_created",
                            AuditEvent.resource_id == str(intent.id),
                        )
                    )
                    == 1
                )
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(
                            AuditEvent.tenant_id == asset.tenant_id,
                            AuditEvent.action == "media.upload_completed",
                            AuditEvent.resource_id == str(asset.id),
                        )
                    )
                    == 1
                )
            assert not tuple(storage.root.glob("*.part"))
        finally:
            await engine.dispose()

    _run_async(run())
