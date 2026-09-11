"""Real binding/audit/retry semantics on SQLite; separate PG tests prove locks."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository, verify_audit_chain_sync
from ac_platform.authorization.policy import CapabilityDenied, CapabilityScope
from ac_platform.catalog.models import Activity, ProgramVersion
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.media.errors import MediaConflict, MediaForbidden, MediaNotFound
from ac_platform.media.models import ActivityMediaBinding, MediaVersion
from ac_platform.media.public_film_manifest import MANIFEST_SHA256 as PUBLIC_DIGEST
from ac_platform.media.public_film_manifest import public_film_media_identity
from ac_platform.media.service import MediaService
from ac_platform.media.signing import MediaSigner
from ac_platform.media.staging_fixture_manifest import MANIFEST_SHA256 as STAGING_DIGEST
from ac_platform.media.staging_fixture_manifest import fixture_media_identity
from ac_platform.media.storage import InMemoryPrivateObjectStorage
from ac_platform.media.studio_contract import StudioVideoSelectionRequest
from ac_platform.media.studio_selection import StudioVideoSelection
from tests.unit.authorization.test_capability_application import assign
from tests.unit.authorization.test_capability_application import state as state  # noqa: F401
from tests.unit.catalog.test_studio_capabilities import CatalogSession
from tests.unit.media.test_studio_library import access, bind, video


@pytest.fixture
async def selection(state):  # noqa: F811
    _, state.editor, state.write_grant = await access(state)
    await assign(
        state,
        permission="catalog_read",
        scope=CapabilityScope("program", state.academy, state.program),
    )
    now = datetime.now(UTC)
    state.db.add(
        IdentitySession(
            id=state.editor.session_id,
            person_id=state.editor.person_id,
            token_hash=b"s" * 32,
            created_at=now,
            expires_at=now + timedelta(hours=1),
            selected_tenant_id=state.academy,
        )
    )
    state.db.flush()
    state.asset, state.version = video(state, filename="My approved lesson.mp4")
    historical = bind(state, state.asset, state.version, binding_state="revoked")
    state.activity_id = historical.activity_id
    signer = MediaSigner("studio-selection-synthetic-test-key-32bytes")
    state.service = MediaService(
        storage=InMemoryPrivateObjectStorage(signer),
        signer=signer,
        webhook_secret="studio-selection-synthetic-webhook-32bytes",  # noqa: S106
    )
    state.database = CatalogSession(state.db)
    state.selection = StudioVideoSelection(state.database, state.service)
    return state


def body(state, *, expected=None, asset=None, version=None, reference="Reviewed lesson source"):
    return StudioVideoSelectionRequest(
        asset_id=asset or state.asset.id,
        version_id=version or state.version.id,
        expected_binding_id=expected,
        approval_reference=reference,
    )


async def save(state, request=None, key=None, **overrides):
    return await state.selection.select(
        state.editor,
        program_id=overrides.get("program", state.program),
        activity_id=overrides.get("activity", state.activity_id),
        body=request or body(state),
        idempotency_key=key or uuid4().hex,
    )


def counts(state):
    return tuple(
        state.db.scalar(select(func.count()).select_from(model))
        for model in (ActivityMediaBinding, AuditEvent)
    )


async def test_scoped_learner_can_approve_reload_and_retry_without_role_escalation(selection):
    state = selection
    before = counts(state)
    key = uuid4().hex
    saved = await save(state, key=key)
    assert saved.state == "approved" and not saved.replayed
    assert counts(state) == (before[0] + 1, before[1] + 1)
    assert not state.editor.permissions
    current = await state.selection.current(
        state.editor, program_id=state.program, activity_id=state.activity_id
    )
    assert current.binding.binding_id == saved.binding_id
    assert current.binding.label == "My approved lesson.mp4"
    assert "test-private" not in current.model_dump_json()
    retry = await save(state, key=key)
    assert retry.binding_id == saved.binding_id and retry.replayed
    assert counts(state) == (before[0] + 1, before[1] + 1)
    assert verify_audit_chain_sync(state.db, state.academy).valid


async def test_explicit_replacement_preserves_history_and_old_receipt_remains_resolvable(selection):
    state = selection
    first_key = uuid4().hex
    first = await save(state, key=first_key)
    replacement_asset, replacement_version = video(state)
    request = body(
        state, expected=first.binding_id, asset=replacement_asset.id, version=replacement_version.id
    )
    second = await save(state, request)
    original = state.db.get(ActivityMediaBinding, first.binding_id)
    assert original.state == "superseded" and original.superseded_at is not None
    assert (
        state.db.get(ActivityMediaBinding, second.binding_id).supersedes_binding_id
        == first.binding_id
    )
    retry = await save(state, key=first_key)
    assert retry.binding_id == first.binding_id and retry.state == "superseded" and retry.replayed


async def test_stale_expected_and_reused_key_do_not_change_anything(selection):
    state = selection
    key = uuid4().hex
    saved = await save(state, key=key)
    before = counts(state)
    for request, retry_key in [
        (body(state), None),
        (body(state, expected=uuid4()), None),
        (body(state, reference="Other intent"), key),
    ]:
        with pytest.raises(MediaConflict):
            await save(state, request, key=retry_key)
    assert counts(state) == before
    assert state.db.get(ActivityMediaBinding, saved.binding_id).state == "approved"


async def test_receipt_retry_still_requires_fresh_course_authority(selection):
    state = selection
    key = uuid4().hex
    await save(state, key=key)
    await state.app.revoke(
        state.actor, command_id=uuid4(), grant_id=state.write_grant.id, reason="Assignment ended"
    )
    with pytest.raises(CapabilityDenied):
        await save(state, key=key)


@pytest.mark.parametrize(
    "scope",
    [
        "foreign-program",
        "foreign-activity",
        "missing-activity",
        "private-video",
        "foreign-tenant-video",
    ],
)
async def test_scope_cannot_be_expanded_by_browser_ids(selection, scope):
    state = selection
    request, overrides = body(state), {}
    if scope == "foreign-program":
        overrides["program"] = state.second
    elif scope == "foreign-activity":
        overrides["activity"] = bind(
            state, state.asset, state.version, program=state.second
        ).activity_id
    elif scope == "missing-activity":
        overrides["activity"] = uuid4()
    else:
        asset, version = video(
            state,
            owner=state.manager if scope == "private-video" else state.stranger,
            tenant=state.academy if scope == "private-video" else state.other,
        )
        request = body(state, asset=asset.id, version=version.id)
    before = counts(state)
    with pytest.raises((CapabilityDenied, MediaForbidden, MediaNotFound)):
        await save(state, request, **overrides)
    assert counts(state) == before


async def test_tenant_wide_grant_does_not_make_unbound_other_instructor_upload_a_picker_choice(
    selection,
):
    state = selection
    await assign(state, permission="catalog_write")
    asset, version = video(state, owner=state.manager)
    with pytest.raises(MediaForbidden):
        await save(state, body(state, asset=asset.id, version=version.id))


async def test_other_instructor_video_requires_current_exact_course_approval(selection):
    state = selection
    asset, version = video(state, owner=state.manager)
    donor = bind(state, asset, version, version_number=2, status="superseded")
    saved = await save(state, body(state, asset=asset.id, version=version.id))
    assert saved.asset_id == asset.id
    donor.state = "superseded"
    state.db.flush()
    # The target now supplies its own same-course approval. A different private
    # version is never admitted through that old source identity.
    version.state = "retired"
    state.db.flush()
    with pytest.raises(MediaConflict):
        await save(
            state, body(state, expected=saved.binding_id, asset=asset.id, version=version.id)
        )


async def test_direct_selection_rejects_an_owned_ready_version_that_is_no_longer_current(selection):
    state = selection
    current = MediaVersion(
        id=uuid4(),
        tenant_id=state.academy,
        asset_id=state.asset.id,
        version_number=2,
        purpose="video",
        state="ready",
        content_type="video/mp4",
        declared_bytes=2000,
        actual_bytes=2000,
        object_key=f"test-private/{uuid4()}",
        supersedes_version_id=state.version.id,
    )
    # Synthetic version history exercises the write seam without a picker read.
    state.db.add(current)
    state.db.flush()
    state.asset.current_version_id = current.id
    state.db.flush()
    before = counts(state)

    with pytest.raises(MediaConflict, match="selected video changed"):
        await save(state)

    assert counts(state) == before
    assert state.asset.current_version_id == current.id
    assert state.version.state == "ready"


@pytest.mark.parametrize("target", ["asset", "version"])
@pytest.mark.parametrize("lifecycle", ["expected", "uploading", "processing", "failed", "retired"])
async def test_direct_selection_rejects_every_nonready_source_state(selection, target, lifecycle):
    state = selection
    source = state.asset if target == "asset" else state.version
    source.state = lifecycle
    state.db.flush()
    before = counts(state)

    with pytest.raises(MediaConflict, match="selected video changed"):
        await save(state)

    assert counts(state) == before
    assert source.state == lifecycle


@pytest.mark.parametrize("target", ["asset", "version"])
async def test_direct_selection_rejects_a_nonvideo_asset_or_version(selection, target):
    state = selection
    source = state.asset if target == "asset" else state.version
    source.purpose = "image"
    state.db.flush()
    before = counts(state)

    with pytest.raises(MediaConflict, match="selected video changed"):
        await save(state)

    assert counts(state) == before
    assert source.purpose == "image"


@pytest.mark.parametrize(
    "identity,digest",
    [
        (public_film_media_identity, PUBLIC_DIGEST),
        (fixture_media_identity, STAGING_DIGEST),
    ],
)
@pytest.mark.parametrize("film", ["bbb-4k-30-normal", "caminandes-gran-dillama-1080p"])
@pytest.mark.parametrize("reserved", ["asset", "version", "both"])
async def test_direct_selection_denies_owned_ready_technical_media(
    selection, identity, digest, film, reserved
):
    state = selection
    asset_id, version_id = identity(state.academy, digest, film)
    asset, version = video(
        state,
        asset_id=asset_id if reserved in {"asset", "both"} else uuid4(),
        version_id=version_id if reserved in {"version", "both"} else uuid4(),
    )
    before = counts(state)

    with pytest.raises(MediaForbidden, match="Technical demonstration films"):
        await save(state, body(state, asset=asset.id, version=version.id))

    assert counts(state) == before
    assert asset.state == version.state == "ready"
    assert asset.current_version_id == version.id


@pytest.mark.parametrize(
    "identity,digest",
    [
        (public_film_media_identity, PUBLIC_DIGEST),
        (fixture_media_identity, STAGING_DIGEST),
    ],
)
@pytest.mark.parametrize("film", ["bbb-4k-30-normal", "caminandes-gran-dillama-1080p"])
@pytest.mark.parametrize("reserved", ["asset", "version", "both"])
async def test_ordinary_selection_cannot_replace_a_current_technical_binding(
    selection, identity, digest, film, reserved
):
    state = selection
    asset_id, version_id = identity(state.academy, digest, film)
    asset, version = video(
        state,
        asset_id=asset_id if reserved in {"asset", "both"} else uuid4(),
        version_id=version_id if reserved in {"version", "both"} else uuid4(),
    )
    # A fixture approval is historical input, never an operational bypass.
    activity = state.db.get(Activity, state.activity_id)
    technical = ActivityMediaBinding(
        tenant_id=state.academy,
        asset_id=asset.id,
        version_id=version.id,
        activity_id=activity.id,
        module_id=activity.module_id,
        program_id=activity.program_id,
        program_version_id=activity.program_version_id,
        program_scope=activity.scope,
        program_owner_key=activity.owner_key,
        activity_version=f"activity:{activity.id}",
        state="approved",
        approval_reference="Synthetic technical-film approval",
        approved_by_person_id=state.manager,
        idempotency_key=uuid4().hex,
        request_fingerprint="a" * 64,
    )
    state.db.add(technical)
    state.db.flush()
    state.db.refresh(technical)
    before = counts(state)
    history = (
        technical.asset_id,
        technical.version_id,
        technical.approved_at,
        technical.approval_reference,
        technical.updated_at,
    )

    with pytest.raises(MediaForbidden, match="dedicated publication workflow"):
        await save(state, body(state, expected=technical.id), activity=technical.activity_id)

    assert counts(state) == before
    assert technical.state == "approved"
    assert technical.superseded_at is None
    assert technical.revoked_at is None
    assert (
        technical.asset_id,
        technical.version_id,
        technical.approved_at,
        technical.approval_reference,
        technical.updated_at,
    ) == history


async def test_draft_activity_is_not_silently_published_by_video_approval(selection):
    state = selection
    activity = state.db.get(Activity, state.activity_id)
    # Separate synthetic catalog version, not mutation of published runtime data.
    draft = bind(
        state, state.asset, state.version, status="draft", version_number=2, binding_state="revoked"
    )
    with pytest.raises(MediaConflict, match="Publish"):
        await save(state, activity=draft.activity_id)
    assert state.db.get(ProgramVersion, draft.program_version_id).status == "draft"
    assert state.db.get(ProgramVersion, activity.program_version_id).status == "published"


async def test_audit_failure_rolls_back_binding_and_prior_supersession(selection, monkeypatch):
    state = selection
    first = await save(state)
    before = counts(state)

    async def refuse(*_args, **_kwargs):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(AuditRepository, "append_for_actor", refuse)
    with pytest.raises(RuntimeError, match="audit failure"):
        await save(state, body(state, expected=first.binding_id))
    assert counts(state) == before
    assert state.db.get(ActivityMediaBinding, first.binding_id).state == "approved"


async def test_forged_or_expired_lease_never_admits_a_binder_call(selection, monkeypatch):
    state = selection
    original = state.service.bind_activity_media
    captured = []

    def record(database, actor, request, **kwargs):
        captured.append((database, actor, request, kwargs["studio_authorization"]))
        return original(database, actor, request, **kwargs)

    monkeypatch.setattr(state.service, "bind_activity_media", record)
    await save(state)
    database, actor, request, lease = captured[0]
    for invalid in (object(), lease, replace(lease, active=True, seal=object())):
        with pytest.raises(MediaForbidden):
            original(
                database, actor, request, idempotency_key=uuid4().hex, studio_authorization=invalid
            )
