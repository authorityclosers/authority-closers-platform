"""Real relational admission/retry proof; transport and encoding are not simulated as done."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository, verify_audit_chain_sync
from ac_platform.authorization.policy import CapabilityDenied
from ac_platform.identity.models import Person
from ac_platform.media.errors import (
    MediaConflict,
    MediaForbidden,
    MediaNotFound,
    MediaQuotaExceeded,
    MediaStorageUnavailable,
)
from ac_platform.media.models import (
    MediaAsset,
    MediaQuotaUsage,
    MediaUploadIntent,
    MediaVersion,
    StudioVideoUpload,
)
from ac_platform.media.studio_upload import StudioVideoUploadRequest, StudioVideoUploads
from ac_platform.media.video_file_storage import VideoFileStorage
from tests.unit.authorization.test_capability_application import assign
from tests.unit.authorization.test_capability_application import state as state  # noqa: F401
from tests.unit.media.test_studio_selection import selection as selection  # noqa: F401


@pytest.fixture(autouse=True)
def genuine_studio_video_issuer(request, tmp_path):
    if "selection" not in request.fixturenames:
        yield
        return
    state = request.getfixturevalue("selection")
    previous = state.service.storage
    state.service.storage = VideoFileStorage(
        root=(tmp_path / "video-objects").resolve(),
        max_object_bytes=1024 * 1024,
        max_store_bytes=4 * 1024 * 1024,
    )
    try:
        yield
    finally:
        state.service.storage = previous


def body(**overrides):
    return StudioVideoUploadRequest(
        **{
            "filename": "My lesson.mp4",
            "content_type": "video/mp4",
            "content_length": 2000,
            "checksum_sha256": "a" * 64,
            **overrides,
        }
    )


def counts(state):
    return tuple(
        state.db.scalar(select(func.count()).select_from(model))
        for model in (
            MediaAsset,
            MediaVersion,
            MediaUploadIntent,
            StudioVideoUpload,
            AuditEvent,
            MediaQuotaUsage,
        )
    )


async def create(state, *, key="first-video", request=None, actor=None, program=None):
    return await StudioVideoUploads(state.database, state.service).create(
        actor or state.editor,
        program_id=program or state.program,
        body=request or body(),
        idempotency_key=key,
    )


async def status(state, upload, *, actor=None, program=None):
    return await StudioVideoUploads(state.database, state.service).status(
        actor or state.editor,
        program_id=program or state.program,
        upload_id=upload.upload_id,
    )


async def test_scoped_coach_creates_upload_without_gaining_permissions_or_claiming_ready(selection):
    state = selection
    assert state.editor.permissions == frozenset()
    result = await create(state)
    receipt = state.db.get(StudioVideoUpload, result.upload_id)
    assert receipt.tenant_id == state.academy and receipt.program_id == state.program
    assert state.editor.permissions == frozenset()
    actual = await status(state, result)
    assert actual.state == "uploading" and actual.uploaded_bytes is None
    assert actual.duration_seconds is None and actual.width is None
    assert actual.label == "My lesson.mp4"
    assert (
        not {"object_key", "upload_url", "checksum_sha256", "processing_error"}
        & actual.model_dump().keys()
    )
    assert verify_audit_chain_sync(state.db, state.academy).valid


async def test_exact_retry_preserves_admission_audit_quota_asset_and_version(selection):
    state = selection
    first = await create(state)
    before = counts(state)
    usage = state.db.scalar(select(MediaQuotaUsage))
    quota = (usage.upload_count, usage.bytes_reserved)
    retry = await create(state)
    assert (retry.upload_id, retry.media_id, retry.media_version_id) == (
        first.upload_id,
        first.media_id,
        first.media_version_id,
    )
    assert counts(state) == before and quota == (usage.upload_count, usage.bytes_reserved)


@pytest.mark.parametrize(
    "changed_request",
    [body(filename="Other.mp4"), body(content_length=3000), body(checksum_sha256="b" * 64)],
)
async def test_same_key_different_file_conflicts_without_mutation(selection, changed_request):
    state = selection
    await create(state)
    before = counts(state)
    with pytest.raises(MediaConflict):
        await create(state, request=changed_request)
    assert counts(state) == before


async def test_other_assigned_course_cannot_reuse_key_or_read_upload(selection):
    state = selection
    await assign(state, permission="catalog_read")
    await assign(state, permission="catalog_write")
    first = await create(state)
    before = counts(state)
    with pytest.raises(MediaConflict):
        await create(state, program=state.second)
    with pytest.raises(MediaNotFound):
        await status(state, first, program=state.second)
    assert counts(state) == before


async def test_fresh_program_authority_required_even_for_owner_retry_and_status(selection):
    state = selection
    first = await create(state)
    await state.app.revoke(
        state.actor,
        grant_id=state.write_grant.id,
        command_id=uuid4(),
        reason="End synthetic assignment",
    )
    before = counts(state)
    for operation in (create(state), status(state, first)):
        with pytest.raises(CapabilityDenied):
            await operation
    assert counts(state) == before


async def test_claimed_manager_permissions_do_not_admit_an_unassigned_course(selection):
    state = selection
    forged = replace(state.editor, permissions=frozenset({"catalog_write", "catalog_read"}))
    before = counts(state)
    with pytest.raises(CapabilityDenied):
        await create(state, actor=forged, program=state.second)
    with pytest.raises(CapabilityDenied):
        await create(state, actor=replace(forged, tenant_id=state.other))
    assert counts(state) == before


async def test_another_instructor_cannot_read_owners_upload_even_with_course_permission(selection):
    state = selection
    first = await create(state)
    for permission in ("catalog_read", "catalog_write"):
        await assign(state, subject_person_id=state.manager, permission=permission)
    other = replace(state.editor, person_id=state.manager)
    with pytest.raises(MediaNotFound):
        await status(state, first, actor=other)


async def test_disabled_identity_cannot_refresh_upload_target(selection):
    state = selection
    await create(state)
    state.db.get(Person, state.editor.person_id).status = "suspended"
    state.db.flush()
    with pytest.raises(CapabilityDenied):
        await create(state)


@pytest.mark.parametrize("expired", [True, False])
async def test_expired_or_processing_upload_does_not_issue_another_byte_target(
    selection, expired, monkeypatch
):
    state = selection
    first = await create(state)
    intent = state.db.get(MediaUploadIntent, first.upload_id)
    if expired:
        intent.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    else:
        intent.state = "processing"
    state.db.flush()

    def forbidden(**kwargs):
        pytest.fail("closed upload must not call provider for a byte target")

    monkeypatch.setattr(state.service.storage, "create_studio_video_upload_intent", forbidden)
    with pytest.raises(MediaConflict):
        await create(state)


async def test_audit_failure_rolls_back_intent_asset_quota_and_course_admission(
    selection, monkeypatch
):
    state = selection
    before = counts(state)

    async def fail(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(AuditRepository, "append_for_actor", fail)
    with pytest.raises(RuntimeError):
        await create(state)
    assert counts(state) == before


async def test_storage_failure_rolls_back_new_rows(selection, monkeypatch):
    state = selection
    before = counts(state)

    def fail(**kwargs):
        raise OSError("synthetic storage failure")

    monkeypatch.setattr(state.service.storage, "create_studio_video_upload_intent", fail)
    with pytest.raises(MediaStorageUnavailable):
        await create(state)
    assert counts(state) == before


async def test_upload_byte_quota_is_not_bypassed_by_studio_authorization(selection):
    before = counts(selection)
    with pytest.raises(MediaQuotaExceeded):
        await create(selection, request=body(content_length=selection.service.max_upload_bytes + 1))
    assert counts(selection) == before


async def test_plain_service_and_forged_lease_still_deny_scoped_actor(selection):
    state = selection
    before = counts(state)
    for kwargs in ({}, {"studio_authorization": object()}):
        with pytest.raises(MediaForbidden):
            state.service.create_upload_intent(
                state.db, state.editor, body().intent_request(), idempotency_key="forged", **kwargs
            )
    assert counts(state) == before


async def test_exact_lease_cannot_be_replayed_after_invocation(selection, monkeypatch):
    state = selection
    original = state.service.create_upload_intent
    captured = []

    def intercept(*args, **kwargs):
        captured.append(kwargs["studio_authorization"])
        return original(*args, **kwargs)

    monkeypatch.setattr(state.service, "create_upload_intent", intercept)
    await create(state)
    before = counts(state)
    with pytest.raises(MediaForbidden):
        original(
            state.db,
            state.editor,
            body().intent_request(),
            idempotency_key="first-video",
            studio_authorization=captured[0],
        )
    assert counts(state) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("filename", "../lesson.mp4"),
        ("filename", " "),
        ("filename", "bad\x00.mp4"),
        ("content_length", True),
        ("content_length", "2000"),
        ("content_length", 0),
        ("checksum_sha256", "bad"),
        ("content_type", "image/png"),
        ("asset_id", str(uuid4())),
        ("tenant_id", str(uuid4())),
        ("purpose", "avatar"),
    ],
)
def test_client_cannot_invent_scope_or_upload_non_video(field, value):
    with pytest.raises(ValidationError):
        body(**{field: value})


@pytest.mark.parametrize("operation", ["move", "delete"])
async def test_course_admission_history_is_immutable(selection, operation):
    state = selection
    first = await create(state)
    with pytest.raises(ValueError), state.db.begin_nested():
        admission = state.db.get(StudioVideoUpload, first.upload_id)
        if operation == "move":
            admission.program_id = state.second
        else:
            state.db.delete(admission)
        state.db.flush()
