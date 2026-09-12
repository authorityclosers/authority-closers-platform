"""Same-host Studio video issuer over canonical upload admission."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.authorization.policy import CapabilityDenied
from ac_platform.media.errors import MediaConflict, MediaForbidden, MediaStorageUnavailable
from ac_platform.media.models import (
    MediaAsset,
    MediaQuotaUsage,
    MediaUploadIntent,
    MediaVersion,
    StudioVideoUpload,
)
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import InMemoryPrivateObjectStorage, StudioVideoStorageUploadIntent
from ac_platform.media.studio_upload import StudioVideoUploadRequest, StudioVideoUploads
from ac_platform.media.video_file_storage import VideoFileStorage
from tests.unit.authorization.test_capability_application import state as state  # noqa: F401
from tests.unit.media.test_studio_selection import selection as selection  # noqa: F401


def _storage(state, tmp_path: Path) -> VideoFileStorage:
    storage = VideoFileStorage(
        root=(tmp_path / "video-objects").resolve(),
        max_object_bytes=1024 * 1024,
        max_store_bytes=4 * 1024 * 1024,
    )
    state.service.storage = storage
    return storage


def _body(**overrides: object) -> StudioVideoUploadRequest:
    return StudioVideoUploadRequest(
        **{
            "filename": "Course lesson.mp4",
            "content_type": "video/mp4",
            "content_length": 4096,
            "checksum_sha256": "A" * 64,
            **overrides,
        }
    )


async def _create(state, *, key: str = "same-host-video", program_id=None):
    return await StudioVideoUploads(state.database, state.service).create(
        state.editor,
        program_id=program_id or state.program,
        body=_body(),
        idempotency_key=key,
    )


def _counts(state) -> tuple[int, ...]:
    return tuple(
        state.db.scalar(select(func.count()).select_from(model))
        for model in (
            MediaAsset,
            MediaVersion,
            MediaUploadIntent,
            StudioVideoUpload,
            MediaQuotaUsage,
            AuditEvent,
        )
    )


async def test_issuer_returns_exact_current_host_route_and_canonical_envelope(selection, tmp_path):
    state = selection
    _storage(state, tmp_path)
    result = await _create(state)
    intent = state.db.get(MediaUploadIntent, result.upload_id)
    admission = state.db.get(StudioVideoUpload, result.upload_id)

    assert result.upload_url == (
        f"/v1/admin/studio/programs/{state.program}/video-uploads/{result.upload_id}/bytes"
    )
    assert result.upload_headers == {
        "content-type": "video/mp4",
        "content-length": "4096",
        "x-content-sha256": "a" * 64,
    }
    assert intent.id == result.upload_id
    assert intent.actor_person_id == state.editor.person_id
    assert intent.tenant_id == state.academy
    assert intent.checksum_sha256 == "a" * 64
    assert admission.program_id == state.program
    assert result.object_key.startswith(f"tenants/{state.academy}/media/video/")


async def test_exact_replay_returns_same_ids_route_and_headers(selection, tmp_path):
    state = selection
    _storage(state, tmp_path)
    first = await _create(state)
    before = _counts(state)
    replay = await _create(state)

    assert replay == first
    assert _counts(state) == before


async def test_expired_foreign_or_stale_authority_never_reissues_route(
    selection, tmp_path, monkeypatch
):
    state = selection
    storage = _storage(state, tmp_path)
    first = await _create(state)
    intent = state.db.get(MediaUploadIntent, first.upload_id)
    intent.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    state.db.flush()

    def forbidden(**_kwargs):
        pytest.fail("closed or unauthorized admission reached the issuer")

    monkeypatch.setattr(storage, "create_studio_video_upload_intent", forbidden)
    with pytest.raises(MediaConflict):
        await _create(state)
    with pytest.raises(CapabilityDenied):
        await _create(state, key="foreign-course", program_id=state.second)
    await state.app.revoke(
        state.actor,
        grant_id=state.write_grant.id,
        command_id=uuid4(),
        reason="Synthetic assignment ended",
    )
    with pytest.raises(CapabilityDenied):
        await _create(state, key="stale-authority")


async def test_issuer_or_audit_failure_rolls_back_every_canonical_row(
    selection, tmp_path, monkeypatch
):
    state = selection
    storage = _storage(state, tmp_path)
    before = _counts(state)

    def fail_issuer(**_kwargs):
        raise OSError("synthetic issuer failure")

    original = storage.create_studio_video_upload_intent
    monkeypatch.setattr(storage, "create_studio_video_upload_intent", fail_issuer)
    with pytest.raises(MediaStorageUnavailable):
        await _create(state, key="failed-issuer")
    assert _counts(state) == before

    issued: list[StudioVideoStorageUploadIntent] = []

    def observe(**kwargs):
        result = original(**kwargs)
        issued.append(result)
        return result

    async def fail_audit(*_args, **_kwargs):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(storage, "create_studio_video_upload_intent", observe)
    monkeypatch.setattr(AuditRepository, "append_for_actor", fail_audit)
    with pytest.raises(RuntimeError):
        await _create(state, key="failed-audit")
    assert len(issued) == 1
    assert state.db.get(MediaUploadIntent, issued[0].upload_id) is None
    assert _counts(state) == before


@pytest.mark.parametrize("mutation", ["extra_header", "route"])
async def test_response_boundary_rejects_mutated_route_or_headers(
    selection, tmp_path, monkeypatch, mutation
):
    state = selection
    storage = _storage(state, tmp_path)
    before = _counts(state)
    original = storage.create_studio_video_upload_intent

    def mutate(**kwargs):
        issued = original(**kwargs)
        if mutation == "extra_header":
            issued.headers["authorization"] = "synthetic credential must not cross boundary"
        else:
            object.__setattr__(issued, "upload_url", "/v1/admin/studio/programs/wrong")
        return issued

    monkeypatch.setattr(storage, "create_studio_video_upload_intent", mutate)
    with pytest.raises(MediaStorageUnavailable, match="does not match"):
        await _create(state, key="mutated-headers")
    assert _counts(state) == before


async def test_non_studio_call_cannot_turn_video_storage_into_an_issuer(selection, tmp_path):
    state = selection
    storage = _storage(state, tmp_path)
    with pytest.raises(MediaForbidden):
        state.service.create_upload_intent(
            state.db,
            state.editor,
            _body().intent_request(),
            idempotency_key="not-studio",
        )
    with pytest.raises(MediaStorageUnavailable):
        storage.create_upload_intent(
            object_key=(f"tenants/{state.academy}/media/video/{uuid4()}/{uuid4()}/original"),
            content_type="video/mp4",
            content_length=4096,
            checksum_sha256="a" * 64,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )

    with pytest.raises(MediaStorageUnavailable):
        StudioVideoStorageUploadIntent(
            upload_url=(f"/v1/admin/studio/programs/{state.program}/video-uploads/{uuid4()}/bytes"),
            object_key=(f"tenants/{state.academy}/media/video/{uuid4()}/{uuid4()}/original"),
            tenant_id=state.academy,
            owner_person_id=state.editor.person_id,
            program_id=state.program,
            upload_id=uuid4(),
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            headers={
                "content-type": "video/mp4",
                "content-length": "4096",
                "x-content-sha256": "a" * 64,
            },
        )


async def test_studio_never_falls_back_to_a_generic_token_upload(selection):
    state = selection
    signer = MediaSigner("issuer-fallback-test-signing-key-32bytes")
    state.service.storage = InMemoryPrivateObjectStorage(signer)
    before = _counts(state)
    with pytest.raises(MediaStorageUnavailable, match="could not issue"):
        await _create(state, key="no-generic-fallback")
    assert _counts(state) == before
