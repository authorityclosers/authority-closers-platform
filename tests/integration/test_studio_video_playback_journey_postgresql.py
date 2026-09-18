"""Real Studio upload-to-enrolled-learner playback on isolated PostgreSQL.

The source is a generated 1.25-second clip and malware inspection uses the
explicit test-only ``SignatureContentScanner``.  FFmpeg, private file storage,
opaque cookie authentication, catalog publication, binding, enrollment and
signed byte delivery are otherwise the application implementations.  The
fixture never supplies a Watch/evidence policy and never writes a live schema.
"""

from __future__ import annotations

import hashlib
import hmac
import shutil
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import ac_platform.http.app as app_module
from ac_platform.application.settings import Settings
from ac_platform.audit.service import AuditRepository
from ac_platform.catalog.models import ProgramVersion
from ac_platform.catalog.services import CatalogService, SqlAlchemyCatalogStore
from ac_platform.enrollment.models import Enrollment, EnrollmentEligibilityFact
from ac_platform.enrollment.services import (
    AsyncEnrollmentApplication,
    FreeEnrollmentCommand,
    ProgramVersionPolicyDeniedError,
)
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.learning.models import (
    ActivityProgress,
    EvidenceSubmission,
    LearningEvidence,
    PlaybackSession,
    VideoWatchInterval,
)
from ac_platform.media.clamav_scanner import ClamAVScannerConfig
from ac_platform.media.models import ActivityMediaBinding
from ac_platform.media.runtime import create_media_runtime
from ac_platform.media.scanner import SignatureContentScanner
from ac_platform.media.studio_video_delivery import compose_local_studio_video_delivery
from ac_platform.media.studio_video_runtime import compose_local_studio_video_runtime
from ac_platform.outbox.repository import RecoveryStateRepository
from ac_platform.tenancy.models import Membership
from tests.integration.test_media_delivery_renewal_postgresql import (
    _run_async,
    postgres_harness,  # noqa: F401 - disposable migrated schema only
)
from tests.integration.test_studio_draft_authoring_postgresql import seed
from tests.integration.test_studio_video_bytes_postgresql import SESSION_PEPPER, _settings
from tests.integration.test_studio_video_ready_postgresql import _clip


@dataclass(frozen=True, slots=True)
class _Learner:
    actor: ActorContext
    token: str
    enrollment_id: UUID | None = None


def _signed_key(value: object, *, origin: str) -> str:
    assert isinstance(value, str)
    parsed = urlsplit(value)
    assert f"{parsed.scheme}://{parsed.netloc}" == origin
    assert parsed.path.startswith("/v1/media/playback/")
    assert not parsed.fragment
    query = parse_qs(parsed.query)
    assert set(query) == {"token"} and len(query["token"]) == 1
    return unquote(parsed.path.removeprefix("/v1/media/playback/"))


def _playlist_children(response: httpx.Response) -> list[str]:
    assert response.content.startswith(b"#EXTM3U")
    return [line for line in response.text.splitlines() if line and not line.startswith("#")]


async def _request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    expected: int = 200,
    **kwargs: Any,
) -> httpx.Response:
    response = await client.request(method, path, **kwargs)
    assert response.status_code == expected, response.text
    return response


async def _seed_activity_and_sessions(
    sessions: Any, state: Any
) -> tuple[UUID, str, list[_Learner]]:
    now = datetime.now(UTC)
    learners = [
        _Learner(
            actor=ActorContext(uuid4(), uuid4(), state.tenant_id),
            token=f"studio-playback-learner-{uuid4().hex}",
        )
        for _ in range(3)
    ]
    async with sessions() as database, database.begin():
        coach = await database.get(Person, state.actors[0].person_id)
        coach_session = await database.get(IdentitySession, state.actors[0].session_id)
        assert coach is not None and coach_session is not None
        coach.email = f"studio-playback-coach-{coach.id.hex}@example.test"
        for learner in learners:
            database.add(
                Person(
                    id=learner.actor.person_id,
                    email=f"studio-playback-{learner.actor.person_id.hex}@example.test",
                    email_verified_at=now,
                )
            )
        await database.flush()
        for learner in learners:
            database.add(
                Membership(
                    tenant_id=state.tenant_id,
                    person_id=learner.actor.person_id,
                    role="learner",
                )
            )
        await database.flush()
        for learner in learners:
            database.add(
                IdentitySession(
                    id=learner.actor.session_id,
                    person_id=learner.actor.person_id,
                    selected_tenant_id=state.tenant_id,
                    token_hash=hmac.new(
                        SESSION_PEPPER.encode(), learner.token.encode(), hashlib.sha256
                    ).digest(),
                    created_at=now - timedelta(minutes=1),
                    expires_at=now + timedelta(hours=1),
                )
            )

        def add_activity(sync: Any) -> tuple[UUID, str]:
            catalog = CatalogService(SqlAlchemyCatalogStore(sync))
            activity = catalog.add_activity(
                state.module_id,
                tenant_id=state.tenant_id,
                kind="VIDEO",
                title="Actual uploaded Studio video",
                is_required=False,
            )
            version = catalog.get_version(state.version_id, tenant_id=state.tenant_id)
            row = sync.get(ProgramVersion, state.version_id)
            assert row is not None
            row.content_digest = catalog._canonical_content_digest(version)  # noqa: SLF001
            sync.flush()
            current = catalog.get_version(state.version_id, tenant_id=state.tenant_id)
            return activity.id, catalog.publication_etag(current)

        activity_id, etag = await database.run_sync(add_activity)
    return activity_id, etag, learners


async def _enroll_learners(
    sessions: Any,
    state: Any,
    learners: list[_Learner],
) -> list[_Learner]:
    now = datetime.now(UTC)
    enrolled: list[_Learner] = []
    for learner in learners:
        async with sessions() as database, database.begin():
            database.add(
                EnrollmentEligibilityFact(
                    tenant_id=state.tenant_id,
                    person_id=learner.actor.person_id,
                    program_version_id=state.version_id,
                    program_id=state.program_id,
                    program_scope="tenant",
                    program_tenant_id=state.tenant_id,
                    program_owner_key=state.tenant_id,
                    age_gate_passed=True,
                    eligibility_passed=True,
                    prerequisites_satisfied=True,
                    policy_version="isolated-studio-video-playback-test",
                    evidence={"test_only": True},
                    evaluated_at=now,
                )
            )
            await database.flush()
            result = await AsyncEnrollmentApplication(database).enroll_free(
                FreeEnrollmentCommand(
                    actor_person_id=learner.actor.person_id,
                    subject_person_id=learner.actor.person_id,
                    tenant_id=state.tenant_id,
                    program_version_id=state.version_id,
                    idempotency_key=f"studio-playback-enroll-{learner.actor.person_id.hex}",
                ),
                actor=learner.actor,
            )
            enrolled.append(replace(learner, enrollment_id=result.enrollment_id))
    return enrolled


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="requires FFmpeg/ffprobe"
)
def test_studio_upload_publication_binding_and_revocable_learner_playback(
    postgres_harness: Any,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _clip(tmp_path)

    async def run() -> None:
        engine = create_async_engine(
            postgres_harness.schema_url, pool_size=4, max_overflow=0, hide_parameters=True
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            state = await seed(sessions)
            activity_id, publication_etag, learners = await _seed_activity_and_sessions(
                sessions, state
            )
            settings = Settings.model_validate(
                {
                    **_settings().model_dump(),
                    "media_max_upload_bytes": 1024**2,
                    "media_max_processing_output_bytes": 16 * 1024**2,
                    "media_allow_range_requests": True,
                }
            )
            coach_token = f"studio-playback-coach-{uuid4().hex}"
            async with sessions() as database, database.begin():
                coach_session = await database.get(IdentitySession, state.actors[0].session_id)
                assert coach_session is not None
                coach_session.token_hash = hmac.new(
                    SESSION_PEPPER.encode(), coach_token.encode(), hashlib.sha256
                ).digest()
                await RecoveryStateRepository(database).reconcile(
                    actor=replace(
                        state.actors[0],
                        permissions=frozenset({"recovery_reconcile", "global_recovery_reconcile"}),
                    ),
                    reason="Isolated Studio playback runtime fixture",
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
                # Explicit test double: no claim of operational antivirus readiness.
                testing_scanner=SignatureContentScanner(),
            )
            runtime = compose_local_studio_video_delivery(settings, runtime)
            monkeypatch.setattr(app_module, "settings", settings)
            monkeypatch.setattr(app_module, "session_factory", sessions)
            application = app_module.create_app(media_runtime=runtime)
            assert not application.dependency_overrides

            coach_origin = str(settings.coach_app_url).rstrip("/")
            learner_origin = str(settings.public_app_url).rstrip("/")
            coach = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application, raise_app_exceptions=False),
                base_url=coach_origin,
                headers={"Origin": coach_origin},
                cookies={settings.session_cookie_name: coach_token},
            )
            learner_clients = [
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=application, raise_app_exceptions=False),
                    base_url=learner_origin,
                    headers={"Origin": learner_origin},
                    cookies={settings.session_cookie_name: learner.token},
                )
                for learner in learners
            ]
            try:
                base = f"/v1/admin/studio/programs/{state.program_id}"
                activity_path = f"/v1/activities/{activity_id}"
                for client in learner_clients:
                    await _request(client, "GET", activity_path, expected=404)

                source = {
                    "filename": "Actual Studio playback clip.mp4",
                    "content_type": "video/mp4",
                    "content_length": len(data),
                    "checksum_sha256": hashlib.sha256(data).hexdigest(),
                }
                admitted = await _request(
                    coach,
                    "POST",
                    f"{base}/video-uploads",
                    json=source,
                    headers={"Idempotency-Key": "playback-upload"},
                )
                upload = admitted.json()
                await _request(
                    coach,
                    "PUT",
                    upload["upload_url"],
                    expected=204,
                    content=data,
                    headers=upload["upload_headers"],
                )
                await _request(
                    coach,
                    "POST",
                    f"{base}/video-uploads/{upload['upload_id']}/complete",
                    expected=202,
                    headers={"Idempotency-Key": "playback-complete"},
                )
                assert engine.pool.checkedout() == 0
                result = await application.state.studio_video_worker.run_once()
                assert result.claimed == result.succeeded == 1
                assert engine.pool.checkedout() == 0

                selection_path = f"{base}/activities/{activity_id}/video"
                selection = {
                    "asset_id": upload["media_id"],
                    "version_id": upload["media_version_id"],
                    "expected_binding_id": None,
                    "approval_reference": "Explicit isolated playback journey review",
                }
                blocked = await _request(
                    coach,
                    "POST",
                    selection_path,
                    expected=409,
                    json=selection,
                    headers={"Idempotency-Key": "playback-binding-before-publish"},
                )
                assert blocked.json()["code"] == "media_conflict"
                # A learner with a live identity, membership and explicit
                # eligibility still cannot acquire a canonical enrollment in
                # draft content. The failed transaction leaves no partial fact.
                with pytest.raises(ProgramVersionPolicyDeniedError):
                    await _enroll_learners(sessions, state, learners)

                published = await _request(
                    coach,
                    "POST",
                    f"/v1/admin/program-versions/{state.version_id}/publish",
                    json={"reason": "Explicit isolated Studio playback publication"},
                    headers={
                        "If-Match": publication_etag,
                        "Idempotency-Key": "playback-publication",
                    },
                )
                assert published.json()["status"] == "published"
                learners = await _enroll_learners(sessions, state, learners)

                unavailable = await _request(learner_clients[0], "GET", activity_path)
                assert unavailable.headers["cache-control"] == "no-store"
                assert unavailable.json()["media"] == {
                    "state": "unavailable",
                    "reason": "approved_activity_media_binding_unavailable",
                    "binding_id": None,
                    "media_id": None,
                    "media_version_id": None,
                    "activity_version": None,
                    "content_type": None,
                    "duration_seconds": None,
                    "width": None,
                    "height": None,
                    "renditions": [],
                    "captions": [],
                    "delivery": None,
                    "provenance": None,
                    "playback_available": False,
                }

                saved = await _request(
                    coach,
                    "POST",
                    selection_path,
                    json=selection,
                    headers={"Idempotency-Key": "playback-binding"},
                )
                binding_id = UUID(saved.json()["binding_id"])
                assert saved.json()["state"] == "approved"

                descriptors: list[dict[str, Any]] = []
                for client in learner_clients:
                    response = await _request(client, "GET", activity_path)
                    body = response.json()
                    assert response.headers["cache-control"] == "no-store"
                    assert body["allowed_actions"] == []
                    assert body["revision"] == 0
                    media = body["media"]
                    assert media["state"] == "approved" and media["playback_available"] is True
                    assert media["binding_id"] == str(binding_id)
                    assert media["media_id"] == upload["media_id"]
                    assert media["media_version_id"] == upload["media_version_id"]
                    assert media["delivery"]["protocol"] == "hls"
                    descriptors.append(media)

                delivery = descriptors[0]["delivery"]
                progressive_url = delivery["progressive_url"]
                manifest_url = delivery["manifest_url"]
                _signed_key(progressive_url, origin=learner_origin)
                _signed_key(manifest_url, origin=learner_origin)
                progressive = await _request(learner_clients[0], "GET", progressive_url)
                assert progressive.headers["cache-control"] == "private, no-store"
                assert progressive.content
                head = await _request(learner_clients[0], "HEAD", progressive_url)
                assert not head.content
                assert int(head.headers["content-length"]) == len(progressive.content)
                # Enrollment in the same course does not make another person's
                # signed grant reusable; each learner gets a session-bound URL.
                await _request(learner_clients[1], "GET", progressive_url, expected=403)
                ranged = await _request(
                    learner_clients[0],
                    "GET",
                    progressive_url,
                    expected=206,
                    headers={"Range": "bytes=0-127"},
                )
                assert ranged.content == progressive.content[:128]
                assert ranged.headers["content-range"] == f"bytes 0-127/{len(progressive.content)}"

                master = await _request(learner_clients[0], "GET", manifest_url)
                assert master.headers["cache-control"] == "private, no-store"
                variants = _playlist_children(master)
                assert variants
                variant = variants[0]
                _signed_key(variant, origin=learner_origin)
                playlist = await _request(learner_clients[0], "GET", variant)
                children = _playlist_children(playlist)
                assert children
                child = children[0]
                _signed_key(child, origin=learner_origin)
                segment = await _request(learner_clients[0], "GET", child)
                assert segment.content
                assert segment.headers["cache-control"] == "private, no-store"

                # Each denial is independent: three canonical learner sessions
                # avoid restoring a revoked session, enrollment or binding.
                async with sessions() as database, database.begin():
                    session = await database.get(IdentitySession, learners[0].actor.session_id)
                    assert session is not None
                    session.revoked_at = datetime.now(UTC)
                await _request(
                    learner_clients[0],
                    "GET",
                    descriptors[0]["delivery"]["progressive_url"],
                    expected=401,
                )

                async with sessions() as database, database.begin():
                    enrollment = await database.get(Enrollment, learners[1].enrollment_id)
                    assert enrollment is not None
                    enrollment.status = "revoked"
                await _request(
                    learner_clients[1],
                    "GET",
                    descriptors[1]["delivery"]["progressive_url"],
                    expected=403,
                )

                async with sessions() as database, database.begin():
                    binding = await database.get(ActivityMediaBinding, binding_id)
                    assert binding is not None
                    binding.state = "revoked"
                    binding.revoked_at = datetime.now(UTC)
                await _request(
                    learner_clients[2],
                    "GET",
                    descriptors[2]["delivery"]["progressive_url"],
                    expected=403,
                )

                # No progress or watch/evidence policy is inferred by byte reads.
                unchanged = await _request(learner_clients[2], "GET", activity_path)
                assert unchanged.json()["revision"] == 0
                assert unchanged.json()["allowed_actions"] == []
                assert unchanged.json()["media"]["state"] == "unavailable"
                async with sessions() as database:
                    for model in (
                        ActivityProgress,
                        PlaybackSession,
                        VideoWatchInterval,
                        LearningEvidence,
                        EvidenceSubmission,
                    ):
                        assert (
                            await database.scalar(
                                select(func.count())
                                .select_from(model)
                                .where(model.tenant_id == state.tenant_id)
                            )
                            == 0
                        )
            finally:
                await coach.aclose()
                for client in learner_clients:
                    await client.aclose()
        finally:
            await engine.dispose()

    _run_async(run())
