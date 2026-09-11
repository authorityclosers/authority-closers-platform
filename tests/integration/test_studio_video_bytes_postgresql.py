"""Real PostgreSQL authority boundaries around Studio video byte streaming.

The real same-host issuer and byte transport share one filesystem adapter; no
adapter is swapped to obtain a placeholder admission. All database state lives
in the disposable migrated schema supplied by ``postgres_harness``. This test
composition does not enable uploads in application startup.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.requests import Request

from ac_platform.application.settings import Settings
from ac_platform.audit.service import AuditRepository
from ac_platform.authorization.application import CapabilityApplication
from ac_platform.authorization.models import CapabilityGrant
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.studio_media import install_studio_media_http
from ac_platform.http.studio_video_bytes import StudioVideoByteTransport
from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.media.api_contracts import UploadIntentResponse
from ac_platform.media.models import MediaAsset, MediaLifecycle, MediaUploadIntent, MediaVersion
from ac_platform.media.service import MediaService
from ac_platform.media.signing import MediaSigner
from ac_platform.media.studio_upload import StudioVideoUploadRequest, StudioVideoUploads
from ac_platform.media.video_file_storage import VideoFileStorage
from ac_platform.tenancy.models import Membership, Tenant
from tests.integration.test_media_delivery_renewal_postgresql import (
    _run_async,
    postgres_harness,  # noqa: F401 - shared isolated migrated schema
)
from tests.integration.test_studio_draft_authoring_postgresql import seed

SESSION_PEPPER = "studio-video-bytes-session-pepper-long-enough"
UPLOAD_TOKEN = "studio-video-bytes-synthetic-session-token-0123456789"  # noqa: S105
MANAGER_TOKEN = "studio-video-bytes-synthetic-manager-token-0123456789"  # noqa: S105
BODY = b"test"


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        database_migrator_url="postgresql+psycopg://unused:unused@localhost/unused",
        session_token_pepper=SESSION_PEPPER,  # noqa: S105 - disposable local fixture
        oauth_transaction_secret="studio-video-bytes-oauth-secret-long-enough",  # noqa: S106
        public_app_url="https://app.studio-bytes.test",
        admin_app_url="https://admin.studio-bytes.test",
        coach_app_url="https://coach.studio-bytes.test",
        api_url="https://api.studio-bytes.test",
        session_cookie_name="ac_session",
    )


def _scope(
    settings: Settings, *, program_id: UUID, upload_id: UUID, token: str
) -> dict[str, object]:
    path = f"/v1/admin/studio/programs/{program_id}/video-uploads/{upload_id}/bytes"
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "PUT",
        "scheme": "https",
        "path": path,
        "raw_path": path.encode("ascii"),
        "root_path": "",
        "query_string": b"",
        "headers": [
            (b"host", settings.coach_app_url.host.encode("ascii")),
            (b"origin", str(settings.coach_app_url).rstrip("/").encode("ascii")),
            (b"cookie", f"{settings.session_cookie_name}={token}".encode("ascii")),
            (b"content-type", b"video/mp4"),
            (b"content-length", str(len(BODY)).encode("ascii")),
            (b"x-content-sha256", hashlib.sha256(BODY).hexdigest().encode("ascii")),
        ],
        "client": ("127.0.0.1", 43210),
        "server": (settings.coach_app_url.host, 443),
    }


class _BodyReceive:
    def __init__(
        self,
        *,
        paused: asyncio.Event | None = None,
        release: asyncio.Event | None = None,
        auth_closed: Callable[[], bool] | None = None,
    ):
        self._index = 0
        self.paused = paused
        self.release = release
        self.auth_closed = auth_closed
        self.first_seen_after_auth_close = False

    async def __call__(self) -> dict[str, object]:
        if self._index == 0:
            self._index += 1
            self.first_seen_after_auth_close = self.auth_closed is None or self.auth_closed()
            assert self.first_seen_after_auth_close
            return {"type": "http.request", "body": BODY[:2], "more_body": True}
        if self._index == 1:
            self._index += 1
            if self.paused is not None:
                self.paused.set()
                assert self.release is not None
                await self.release.wait()
            return {"type": "http.request", "body": BODY[2:], "more_body": True}
        return {"type": "http.request", "body": b"", "more_body": False}


async def _call_application(
    application: FastAPI,
    scope: dict[str, object],
    receive: Callable[[], Awaitable[dict[str, object]]],
) -> tuple[int, bytes]:
    status: int | None = None
    body = bytearray()

    async def send(message: dict[str, object]) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            response_status = message["status"]
            assert isinstance(response_status, int)
            status = response_status
        elif message["type"] == "http.response.body":
            response_body = message.get("body", b"")
            assert isinstance(response_body, bytes)
            body.extend(response_body)

    await application(scope, receive, send)
    assert status is not None
    return status, bytes(body)


async def _add_revoke_manager(
    sessions: async_sessionmaker[AsyncSession], state: SimpleNamespace
) -> tuple[ActorContext, UUID]:
    """Create only disposable fixture rows; revoke itself uses the real command."""

    now = datetime.now(UTC)
    operations_tenant_id, manager_id, manager_session_id = uuid4(), uuid4(), uuid4()
    manager = ActorContext(manager_id, manager_session_id, operations_tenant_id)
    token_hash = hmac.new(
        SESSION_PEPPER.encode("ascii"), MANAGER_TOKEN.encode("ascii"), hashlib.sha256
    ).digest()
    async with sessions() as database, database.begin():
        database.add(
            Tenant(id=operations_tenant_id, slug=operations_tenant_id.hex, name="Operations")
        )
        database.add(
            Person(
                id=manager_id,
                email=f"studio-video-bytes-manager-{manager_id.hex}@example.test",
                email_verified_at=now,
            )
        )
        await database.flush()
        database.add(Membership(tenant_id=operations_tenant_id, person_id=manager_id, role="owner"))
        await database.flush()
        database.add(
            IdentitySession(
                id=manager_session_id,
                person_id=manager_id,
                selected_tenant_id=operations_tenant_id,
                token_hash=token_hash,
                created_at=now,
                expires_at=now + timedelta(hours=1),
            )
        )
        await database.flush()
        manager_audit = await AuditRepository(database).append_for_actor(
            manager,
            action="test.studio_video_bytes_manager_fixture",
            resource_type="capability_grant",
            reason="Disposable integration fixture",
        )
        database.add(
            CapabilityGrant(
                id=uuid4(),
                subject_person_id=manager_id,
                permission="platform_access_manage",
                scope_kind="platform",
                tenant_id=None,
                program_id=None,
                granted_by_person_id=manager_id,
                audit_event_id=manager_audit.id,
                reason="Disposable integration fixture",
            )
        )
        await database.flush()
        target_grant_id = await database.scalar(
            select(CapabilityGrant.id).where(
                CapabilityGrant.subject_person_id == state.actors[0].person_id,
                CapabilityGrant.permission == "catalog_write",
                CapabilityGrant.program_id == state.program_id,
            )
        )
        assert target_grant_id is not None
    return manager, target_grant_id


async def _prepare_upload(
    sessions: async_sessionmaker[AsyncSession], state: SimpleNamespace, storage: VideoFileStorage
) -> tuple[UploadIntentResponse, MediaService]:
    signer = MediaSigner("studio-video-bytes-storage-signing-key-32bytes")
    service = MediaService(
        storage=storage,
        signer=signer,
        webhook_secret="studio-video-bytes-webhook-secret-32bytes",  # noqa: S106
    )
    async with sessions() as database, database.begin():
        result = await StudioVideoUploads(database, service).create(
            state.actors[0],
            program_id=state.program_id,
            idempotency_key=f"studio-video-bytes-{uuid4().hex}",
            body=StudioVideoUploadRequest(
                filename="paused-lecture.mp4",
                content_type="video/mp4",
                content_length=len(BODY),
                checksum_sha256=hashlib.sha256(BODY).hexdigest(),
            ),
        )
    return result, service


def _resolver(
    sessions: async_sessionmaker[AsyncSession],
    settings: Settings,
    counters: dict[str, int],
    expected_token: str,
) -> Callable[[Request], AsyncIterator[AuthenticatedTransaction]]:
    @asynccontextmanager
    async def synthetic_real_session_resolver(
        request: Request,
    ) -> AsyncIterator[AuthenticatedTransaction]:
        token = request.cookies.get(settings.session_cookie_name)
        assert token == expected_token
        try:
            async with sessions() as database, database.begin():
                counters["opened"] += 1
                identity = AsyncIdentityApplication(database, token_pepper=SESSION_PEPPER)
                resolved = await identity.resolve_actor(token)
                yield AuthenticatedTransaction(
                    database=database,
                    identity=identity,
                    resolved=resolved,
                    token=token,
                )
        finally:
            counters["closed"] += 1

    async def require_actor(request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        async with synthetic_real_session_resolver(request) as auth:
            yield auth

    return require_actor


async def _run_case(
    postgres_harness: Any,  # noqa: F811
    tmp_path: Path,
    *,
    revoke_while_paused: bool,
) -> tuple[int, bytes, dict[str, int], VideoFileStorage, SimpleNamespace]:
    engine = create_async_engine(postgres_harness.schema_url, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    settings = _settings()
    counters = {"opened": 0, "closed": 0}
    try:
        state = await seed(sessions)
        upload_token = f"studio-video-bytes-synthetic-{state.actors[0].session_id.hex}"
        async with sessions() as database, database.begin():
            session = await database.get(IdentitySession, state.actors[0].session_id)
            person = await database.get(Person, state.actors[0].person_id)
            assert session is not None
            assert person is not None
            person.email = f"studio-video-bytes-{state.actors[0].person_id.hex}@example.test"
            session.token_hash = hmac.new(
                SESSION_PEPPER.encode("ascii"), upload_token.encode("ascii"), hashlib.sha256
            ).digest()
        storage = VideoFileStorage(
            root=tmp_path / "video-objects",
            max_object_bytes=1024 * 1024,
            max_store_bytes=8 * 1024 * 1024,
        )
        upload, admission_service = await _prepare_upload(sessions, state, storage)
        assert upload.upload_url == (
            f"/v1/admin/studio/programs/{state.program_id}/video-uploads/{upload.upload_id}/bytes"
        )
        resolver = _resolver(sessions, settings, counters, upload_token)
        transport = StudioVideoByteTransport(
            storage=storage,
            require_actor=resolver,
            settings=settings,
            idle_seconds=5,
            transfer_seconds=30,
        )
        application = FastAPI()
        register_problem_handlers(application)
        install_studio_media_http(
            application,
            settings=settings,
            require_actor=resolver,
            service=admission_service,
            byte_transport=transport,
        )
        paused = asyncio.Event() if revoke_while_paused else None
        release = asyncio.Event() if revoke_while_paused else None
        receiver = _BodyReceive(
            paused=paused,
            release=release,
            auth_closed=lambda: counters["opened"] == counters["closed"] == 1,
        )
        scope = _scope(
            settings, program_id=state.program_id, upload_id=upload.upload_id, token=upload_token
        )
        request_task = asyncio.create_task(_call_application(application, scope, receiver))
        try:
            if revoke_while_paused:
                assert paused is not None and release is not None
                await asyncio.wait_for(paused.wait(), 5)
                assert counters["opened"] == 1
                async with sessions() as database, database.begin():
                    unlocked_person = await database.scalar(
                        select(Person)
                        .where(Person.id == state.actors[0].person_id)
                        .with_for_update(nowait=True)
                    )
                    assert unlocked_person is not None
                manager, grant_id = await _add_revoke_manager(sessions, state)
                assert manager.tenant_id is not None
                async with sessions() as database, database.begin():
                    await asyncio.wait_for(
                        CapabilityApplication(
                            database, operations_tenant_id=manager.tenant_id
                        ).revoke(
                            manager,
                            command_id=uuid4(),
                            grant_id=grant_id,
                            reason="Synthetic pause revocation",
                        ),
                        5,
                    )
                release.set()
            status, body = await asyncio.wait_for(request_task, 10)
            return status, body, counters, storage, state
        finally:
            if release is not None:
                release.set()
            await asyncio.gather(request_task, return_exceptions=True)
    finally:
        await engine.dispose()


def test_postgresql_streaming_upload_closes_auth_before_body_and_stays_uploading(
    postgres_harness: Any,  # noqa: F811
    tmp_path: Path,
) -> None:  # noqa: F811
    async def run() -> None:
        status, body, counters, storage, state = await _run_case(
            postgres_harness, tmp_path, revoke_while_paused=False
        )
        assert status == 204, body
        assert counters == {"opened": 2, "closed": 2}
        check_engine = create_async_engine(postgres_harness.schema_url)
        try:
            check_sessions = async_sessionmaker(check_engine, expire_on_commit=False)
            async with check_sessions() as database:
                rows = await database.execute(
                    select(MediaUploadIntent, MediaVersion, MediaAsset)
                    .join(MediaVersion, MediaVersion.id == MediaUploadIntent.version_id)
                    .join(MediaAsset, MediaAsset.id == MediaUploadIntent.asset_id)
                    .where(MediaUploadIntent.actor_person_id == state.actors[0].person_id)
                )
                intent, version, asset = rows.one()
                assert (intent.state, version.state, asset.state) == (
                    MediaLifecycle.UPLOADING.value,
                    MediaLifecycle.UPLOADING.value,
                    MediaLifecycle.UPLOADING.value,
                )
                assert version.actual_bytes is None
        finally:
            await check_engine.dispose()
        assert storage.head(intent.object_key) is not None
        assert not list(storage.root.glob("*.part"))

    _run_async(run())


def test_postgresql_streaming_upload_rejects_canonical_revoke_and_cleans_part(
    postgres_harness: Any,  # noqa: F811
    tmp_path: Path,
) -> None:  # noqa: F811
    async def run() -> None:
        status, body, counters, storage, state = await _run_case(
            postgres_harness, tmp_path, revoke_while_paused=True
        )
        assert status == 403
        assert b"authorization_denied" in body
        assert counters == {"opened": 2, "closed": 2}
        assert not list(storage.root.glob("*.part"))
        check_engine = create_async_engine(postgres_harness.schema_url)
        try:
            check_sessions = async_sessionmaker(check_engine, expire_on_commit=False)
            async with check_sessions() as database:
                rows = await database.execute(
                    select(MediaUploadIntent, MediaVersion, MediaAsset)
                    .join(MediaVersion, MediaVersion.id == MediaUploadIntent.version_id)
                    .join(MediaAsset, MediaAsset.id == MediaUploadIntent.asset_id)
                    .where(MediaUploadIntent.actor_person_id == state.actors[0].person_id)
                )
                intent, version, asset = rows.one()
                assert (intent.state, version.state, asset.state) == (
                    MediaLifecycle.UPLOADING.value,
                    MediaLifecycle.UPLOADING.value,
                    MediaLifecycle.UPLOADING.value,
                )
                assert version.actual_bytes is None
        finally:
            await check_engine.dispose()
        assert storage.head(intent.object_key) is None

    _run_async(run())
