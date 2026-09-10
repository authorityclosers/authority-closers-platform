"""Actual app graph, cookie authority, HTTP upload and FFmpeg worker on isolated PG.

Uses a 1.25-second 320x180 generated clip and an explicit test-only signature
scanner. This is not deployed antivirus, browser playback or 4K acceptance.
"""

from __future__ import annotations

import hashlib
import hmac
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import ac_platform.http.app as app_module
from ac_platform.application.settings import Settings
from ac_platform.audit.service import AuditRepository
from ac_platform.catalog.models import ProgramVersion
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.media.clamav_scanner import ClamAVScannerConfig
from ac_platform.media.models import ActivityMediaBinding, MediaRendition, MediaVersion
from ac_platform.media.runtime import create_media_runtime
from ac_platform.media.scanner import SignatureContentScanner
from ac_platform.media.studio_video_runtime import compose_local_studio_video_runtime
from ac_platform.outbox.repository import RecoveryStateRepository
from tests.integration.test_media_delivery_renewal_postgresql import (
    _run_async,
    postgres_harness,  # noqa: F401 - disposable migrated schema only
)
from tests.integration.test_studio_draft_authoring_postgresql import seed
from tests.integration.test_studio_video_bytes_postgresql import SESSION_PEPPER, _settings
from tests.integration.test_studio_video_ready_postgresql import _clip


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="requires FFmpeg/ffprobe"
)
@pytest.mark.parametrize("surface", ["coach", "admin"])
def test_composed_app_upload_reaches_ready_without_binding_or_publication(
    postgres_harness: Any,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
) -> None:
    data = _clip(tmp_path)

    async def run() -> None:
        engine = create_async_engine(postgres_harness.schema_url, pool_size=3, max_overflow=0)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            state = await seed(sessions)
            settings = Settings.model_validate(
                {
                    **_settings().model_dump(),
                    "media_max_upload_bytes": 1024**2,
                    "media_max_processing_output_bytes": 16 * 1024**2,
                }
            )
            token = f"runtime-synthetic-session-{uuid4().hex}"
            async with sessions() as database, database.begin():
                identity = await database.get(IdentitySession, state.actors[0].session_id)
                person = await database.get(Person, state.actors[0].person_id)
                assert identity is not None and person is not None
                person.email = f"runtime-{person.id.hex}@example.test"
                identity.token_hash = hmac.new(
                    SESSION_PEPPER.encode(), token.encode(), hashlib.sha256
                ).digest()
                await RecoveryStateRepository(database).reconcile(
                    actor=replace(
                        state.actors[0],
                        permissions=frozenset({"recovery_reconcile", "global_recovery_reconcile"}),
                    ),
                    reason="Isolated runtime integration fixture",
                    audit=AuditRepository(database),
                    operations_tenant_id=state.tenant_id,
                )
            runtime = compose_local_studio_video_runtime(
                settings,
                create_media_runtime(settings),
                sessions=sessions,
                root=tmp_path / "video-objects",
                max_store_bytes=32 * 1024**2,
                scanner_config=ClamAVScannerConfig(host="127.0.0.1", max_content_bytes=1024**2),
                testing_scanner=SignatureContentScanner(),
            )
            monkeypatch.setattr(app_module, "settings", settings)
            monkeypatch.setattr(app_module, "session_factory", sessions)
            application = app_module.create_app(media_runtime=runtime)
            origin = str(
                settings.coach_app_url if surface == "coach" else settings.admin_app_url
            ).rstrip("/")
            base = f"/v1/admin/studio/programs/{state.program_id}"
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application),
                base_url=origin,
                cookies={settings.session_cookie_name: token},
                headers={"origin": origin},
            ) as client:
                capability = await client.get(f"{base}/video-upload-capability")
                assert capability.status_code == 200, capability.text
                assert capability.json() == {
                    "available": True,
                    "max_source_bytes": 1024**2,
                    "accepted_content_types": ["video/mp4", "video/webm"],
                    "reason": None,
                }
                foreign = await client.get(
                    f"/v1/admin/studio/programs/{uuid4()}/video-upload-capability"
                )
                assert foreign.status_code in {403, 404}
                body = {
                    "filename": "Synthetic runtime clip.mp4",
                    "content_type": "video/mp4",
                    "content_length": len(data),
                    "checksum_sha256": hashlib.sha256(data).hexdigest(),
                }
                admitted = await client.post(
                    f"{base}/video-uploads", json=body, headers={"idempotency-key": "runtime-admit"}
                )
                assert admitted.status_code == 200, admitted.text
                upload = admitted.json()
                sent = await client.put(
                    upload["upload_url"], content=data, headers=upload["upload_headers"]
                )
                assert sent.status_code == 204, sent.text
                assert sent.headers["x-ac-upload-bytes"] == str(len(data))
                assert sent.headers["x-ac-upload-sha256"] == body["checksum_sha256"]
                path = f"{base}/video-uploads/{upload['upload_id']}"
                completed = await client.post(
                    f"{path}/complete", headers={"idempotency-key": "runtime-complete"}
                )
                assert completed.status_code == 202, completed.text
                assert (await client.get(path)).json()["state"] == "processing"
                processing_library = await client.get(f"{base}/videos")
                assert processing_library.status_code == 200, processing_library.text
                assert processing_library.json() == {"items": [], "next_cursor": None}
                assert engine.pool.checkedout() == 0
                result = await application.state.studio_video_worker.run_once()
                assert result.claimed == result.succeeded == 1, result
                status = await client.get(path)
                assert status.status_code == 200, status.text
                ready = status.json()
                assert ready["state"] == "ready"
                assert ready["uploaded_bytes"] == ready["declared_bytes"] == len(data)
                assert (ready["width"], ready["height"]) == (320, 180)
                assert 1.0 <= ready["duration_seconds"] <= 1.5
                library = await client.get(f"{base}/videos")
                assert library.status_code == 200, library.text
                assert library.headers["cache-control"] == "no-store"
                assert library.json() == {
                    "items": [
                        {
                            "asset_id": upload["media_id"],
                            "version_id": upload["media_version_id"],
                            "version_number": 1,
                            "label": body["filename"],
                            "state": "ready",
                            "actual_bytes": len(data),
                            "duration_seconds": ready["duration_seconds"],
                            "width": 320,
                            "height": 180,
                        }
                    ],
                    "next_cursor": None,
                }
                replay = await client.post(
                    f"{path}/complete", headers={"idempotency-key": "runtime-complete"}
                )
                assert replay.status_code == 200, replay.text
                assert replay.json()["state"] == "ready" and replay.json()["replayed"] is True
                assert replay.json()["processing_job_id"] is None
                assert (await application.state.studio_video_worker.run_once()).claimed == 0
            async with sessions() as database:
                version = await database.get(MediaVersion, UUID(upload["media_version_id"]))
                assert version is not None and version.state == "ready"
                renditions = list(
                    await database.scalars(
                        select(MediaRendition).where(MediaRendition.version_id == version.id)
                    )
                )
                assert len(renditions) >= 2
                assert (
                    await database.scalar(select(func.count()).select_from(ActivityMediaBinding))
                    == 0
                )
                course_version = await database.get(ProgramVersion, state.version_id)
                assert course_version is not None and course_version.status == "draft"
            assert engine.pool.checkedout() == 0
        finally:
            await engine.dispose()

    _run_async(run())
