"""Real relational picker isolation via SQLite, not PostgreSQL lock/HTTP proof."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import event

from ac_platform.authorization.policy import CapabilityDenied, CapabilityScope
from ac_platform.catalog.models import Activity, Module, Program, ProgramVersion
from ac_platform.http.auth import ROLE_PERMISSIONS
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.media.errors import MediaConflict
from ac_platform.media.models import (
    ActivityMediaBinding,
    MediaAsset,
    MediaUploadIntent,
    MediaVersion,
)
from ac_platform.media.public_film_manifest import MANIFEST_SHA256 as PUBLIC_DIGEST
from ac_platform.media.public_film_manifest import public_film_media_identity
from ac_platform.media.staging_fixture_manifest import MANIFEST_SHA256 as STAGING_DIGEST
from ac_platform.media.staging_fixture_manifest import fixture_media_identity
from ac_platform.media.studio_library import StudioVideoLibrary, StudioVideoLibraryQuery
from ac_platform.tenancy.models import Membership
from tests.unit.authorization.test_capability_application import assign, bootstrap
from tests.unit.authorization.test_capability_application import state as state  # noqa: F401


async def access(state):
    await bootstrap(state)
    grant = await assign(
        state,
        permission="catalog_write",
        scope=CapabilityScope("program", state.academy, state.program),
    )
    actor = ActorContext(state.learner, uuid4(), state.academy)
    return StudioVideoLibrary(state.app.database), actor, grant


def video(state, *, owner=None, tenant=None, asset_id=None, version_id=None, filename=None):
    tenant = tenant or state.academy
    owner = owner or state.learner
    asset_id, version_id = asset_id or uuid4(), version_id or uuid4()
    asset = MediaAsset(
        id=asset_id,
        tenant_id=tenant,
        owner_person_id=owner,
        purpose="video",
        state="expected",
        current_version_id=None,
    )
    state.db.add(asset)
    state.db.flush()
    version = MediaVersion(
        id=version_id,
        tenant_id=tenant,
        asset_id=asset_id,
        version_number=1,
        purpose="video",
        state="ready",
        content_type="video/mp4",
        declared_bytes=1000,
        actual_bytes=1000,
        object_key=f"test-private/{uuid4()}",
        duration_seconds=10,
        width=1920,
        height=1080,
    )
    state.db.add(version)
    state.db.flush()
    asset.current_version_id = version_id
    asset.state = "ready"
    state.db.flush()
    if filename is not None:
        upload(state, asset, version, filename)
    return asset, version


def upload(state, asset, version, filename, created_at=None, *, intent_id=None):
    intent = MediaUploadIntent(
        id=intent_id or uuid4(),
        tenant_id=asset.tenant_id,
        actor_person_id=asset.owner_person_id,
        asset_id=asset.id,
        version_id=version.id,
        filename=filename,
        object_key=f"test-private/{uuid4()}",
        content_type="video/mp4",
        declared_bytes=1000,
        max_bytes=1000,
        request_fingerprint="a" * 64,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        created_at=created_at or datetime.now(UTC),
        state="ready",
    )
    state.db.add(intent)
    state.db.flush()
    return intent


def bind(
    state,
    asset,
    version,
    *,
    program=None,
    status="published",
    binding_state="approved",
    version_number=1,
):
    program = program or state.program
    catalog_id, module_id, activity_id = uuid4(), uuid4(), uuid4()
    scope = dict(scope="tenant", owner_key=state.academy, tenant_id=state.academy)
    catalog = ProgramVersion(
        id=catalog_id,
        program_id=program,
        version_number=version_number,
        status=status,
        **scope,
    )
    module = Module(
        id=module_id,
        program_id=program,
        program_version_id=catalog_id,
        position=1,
        title="Synthetic module",
        **scope,
    )
    activity = Activity(
        id=activity_id,
        module_id=module_id,
        program_id=program,
        program_version_id=catalog_id,
        position=1,
        kind="VIDEO",
        title="Synthetic lesson",
        **scope,
    )
    # Isolated relational fixture, not an operational publication path.
    state.db.add_all([catalog, module, activity])
    state.db.flush()
    binding = ActivityMediaBinding(
        tenant_id=state.academy,
        asset_id=asset.id,
        version_id=version.id,
        activity_id=activity_id,
        module_id=module_id,
        program_id=program,
        program_version_id=catalog_id,
        program_scope="tenant",
        program_owner_key=state.academy,
        activity_version=f"activity:{activity_id}",
        state=binding_state,
        approval_reference="Synthetic approved fixture",
        approved_by_person_id=state.manager,
        idempotency_key=uuid4().hex,
        request_fingerprint="a" * 64,
    )
    state.db.add(binding)
    state.db.flush()
    return binding


async def test_library_returns_owned_and_exact_course_approved_videos_only(state):
    library, actor, _ = await access(state)
    owned, _ = video(state, filename="My lesson.mp4")
    bound, bound_version = video(state, owner=state.manager, filename="Course lesson.mp4")
    bind(state, bound, bound_version)
    video(state, owner=state.manager, filename="Unrelated private upload.mp4")
    elsewhere, elsewhere_version = video(state, owner=state.manager, filename="Other course.mp4")
    bind(state, elsewhere, elsewhere_version, program=state.second)
    video(state, tenant=state.other, owner=state.stranger, filename="Other tenant.mp4")
    page = await library.list_choices(actor, program_id=state.program)
    assert {item.asset_id for item in page.items} == {owned.id, bound.id}
    assert page.next_cursor is None
    serialized = page.model_dump_json()
    for private in (
        "Unrelated private",
        "Other course",
        "Other tenant",
        "test-private",
        "owner_person",
    ):
        assert private not in serialized
    assert not state.db.new and not state.db.dirty and not state.db.deleted


@pytest.mark.parametrize(
    "permission", [None, "catalog_read", "catalog_publish", "platform_catalog_read"]
)
async def test_permission_denial_precedes_media_query_even_with_forged_permissions(
    state, permission
):
    await bootstrap(state)
    if permission:
        await assign(
            state,
            permission=permission,
            scope=CapabilityScope("platform")
            if permission.startswith("platform")
            else CapabilityScope("program", state.academy, state.program),
        )
    actor = ActorContext(state.learner, uuid4(), state.academy, ROLE_PERMISSIONS["owner"])
    statements = []
    event.listen(
        state.db.get_bind(),
        "before_cursor_execute",
        lambda _c, _u, sql, *_a: statements.append(sql),
    )
    with pytest.raises(CapabilityDenied):
        await StudioVideoLibrary(state.app.database).list_choices(actor, program_id=state.program)
    assert not any("media_assets" in sql for sql in statements)


async def test_another_program_missing_tenant_or_global_program_is_denied(state):
    library, actor, _ = await access(state)
    global_id = uuid4()
    state.db.add(Program(id=global_id, scope="global", slug=global_id.hex, title="Global"))
    state.db.flush()
    for program in (state.second, uuid4(), global_id):
        with pytest.raises(CapabilityDenied):
            await library.list_choices(actor, program_id=program)
    with pytest.raises(CapabilityDenied):
        await library.list_choices(replace(actor, tenant_id=None), program_id=state.program)


async def test_each_cursor_request_rechecks_revocation_and_current_lifecycle(state):
    library, actor, grant = await access(state)
    for i in range(3):
        video(state, asset_id=UUID(int=i + 100))
    first = await library.list_choices(
        actor, program_id=state.program, query=StudioVideoLibraryQuery(limit=1)
    )
    assert first.next_cursor is not None
    await state.app.revoke(
        state.actor, command_id=uuid4(), grant_id=grant.id, reason="Assignment ended"
    )
    with pytest.raises(CapabilityDenied):
        await library.list_choices(
            actor, program_id=state.program, query=StudioVideoLibraryQuery(after=first.next_cursor)
        )


@pytest.mark.parametrize("lifecycle", ["person", "membership", "verified"])
async def test_current_lifecycle_after_a_success_is_required(state, lifecycle):
    library, actor, _ = await access(state)
    await library.list_choices(actor, program_id=state.program)
    if lifecycle == "person":
        state.db.get(Person, state.learner).status = "suspended"
    elif lifecycle == "membership":
        membership = state.db.get(Membership, (state.academy, state.learner))
        membership.status = "inactive"
        membership.ended_at = datetime.now(UTC)
    else:
        state.db.get(Person, state.learner).email_verified_at = None
    state.db.flush()
    with pytest.raises(CapabilityDenied):
        await library.list_choices(actor, program_id=state.program)


async def test_pagination_filters_private_rows_before_limit_and_does_not_duplicate_intents(state):
    library, actor, _ = await access(state)
    now = datetime.now(UTC)
    for i in range(1, 5):
        video(state, asset_id=UUID(int=i), owner=state.manager)
    expected = []
    for i in range(100, 105):
        asset, version = video(state, asset_id=UUID(int=i))
        upload(state, asset, version, "Old name.mp4", now - timedelta(minutes=1))
        upload(state, asset, version, "Current name.mp4", now)
        expected.append(asset.id)
    collected, cursor = [], None
    for expected_size in (2, 2, 1):
        page = await library.list_choices(
            actor, program_id=state.program, query=StudioVideoLibraryQuery(limit=2, after=cursor)
        )
        assert len(page.items) == expected_size
        assert all(item.label == "Current name.mp4" for item in page.items)
        collected.extend(item.asset_id for item in page.items)
        cursor = page.next_cursor
    assert collected == expected and cursor is None
    forged = await library.list_choices(
        actor, program_id=state.program, query=StudioVideoLibraryQuery(after=UUID(int=2), limit=2)
    )
    assert [item.asset_id for item in forged.items] == expected[:2]


@pytest.mark.parametrize(
    "state_value", ["expected", "uploading", "processing", "failed", "retired"]
)
@pytest.mark.parametrize("target", ["asset", "version"])
async def test_unready_media_never_appears(state, state_value, target):
    library, actor, _ = await access(state)
    asset, version = video(state)
    (asset if target == "asset" else version).state = state_value
    state.db.flush()
    assert (await library.list_choices(actor, program_id=state.program)).items == ()


@pytest.mark.parametrize("binding_state", ["superseded", "revoked"])
async def test_noncurrent_binding_cannot_expose_someone_elses_media(state, binding_state):
    library, actor, _ = await access(state)
    asset, version = video(state, owner=state.manager)
    bind(state, asset, version, binding_state=binding_state)
    assert (await library.list_choices(actor, program_id=state.program)).items == ()


async def test_malformed_approval_for_draft_does_not_grant_library_access(state):
    library, actor, _ = await access(state)
    asset, version = video(state, owner=state.manager)
    bind(state, asset, version, status="draft")
    assert (await library.list_choices(actor, program_id=state.program)).items == ()


async def test_all_technical_fixture_identities_are_filtered_before_pagination(state):
    library, actor, _ = await access(state)
    for identity, digest in (
        (public_film_media_identity, PUBLIC_DIGEST),
        (fixture_media_identity, STAGING_DIGEST),
    ):
        for film in ("bbb-4k-30-normal", "caminandes-gran-dillama-1080p"):
            asset_id, version_id = identity(state.academy, digest, film)
            video(state, asset_id=asset_id, version_id=version_id)
    eligible, _ = video(state, asset_id=UUID(int=2**128 - 1))
    page = await library.list_choices(
        actor, program_id=state.program, query=StudioVideoLibraryQuery(limit=1)
    )
    assert [item.asset_id for item in page.items] == [eligible.id]
    assert page.next_cursor is None


@pytest.mark.parametrize("value", [0, 51, True, "2", 1.5, None])
def test_query_rejects_invalid_limit(value):
    with pytest.raises(ValidationError):
        StudioVideoLibraryQuery(limit=value)


@pytest.mark.parametrize(
    "identity,digest",
    [
        (public_film_media_identity, PUBLIC_DIGEST),
        (fixture_media_identity, STAGING_DIGEST),
    ],
)
@pytest.mark.parametrize("film", ["bbb-4k-30-normal", "caminandes-gran-dillama-1080p"])
@pytest.mark.parametrize("reserved", ["asset", "version"])
async def test_partial_technical_identity_is_filtered_before_limit(
    state, identity, digest, film, reserved
):
    library, actor, _ = await access(state)
    asset_id, version_id = identity(state.academy, digest, film)
    video(
        state,
        asset_id=asset_id if reserved == "asset" else UUID(int=1),
        version_id=version_id if reserved == "version" else uuid4(),
    )
    eligible, _ = video(state, asset_id=UUID(int=2**128 - 1))
    page = await library.list_choices(
        actor,
        program_id=state.program,
        query=StudioVideoLibraryQuery(limit=1),
    )
    assert [item.asset_id for item in page.items] == [eligible.id]
    assert page.next_cursor is None


async def test_old_approval_cannot_expose_a_new_source_version_owned_by_another_instructor(state):
    library, actor, _ = await access(state)
    asset, original = video(state, owner=state.manager)
    bind(state, asset, original)
    assert len((await library.list_choices(actor, program_id=state.program)).items) == 1
    replacement = MediaVersion(
        id=uuid4(),
        tenant_id=state.academy,
        asset_id=asset.id,
        version_number=2,
        purpose="video",
        state="ready",
        content_type="video/mp4",
        declared_bytes=2000,
        actual_bytes=2000,
        object_key="test-private/unapproved-replacement",
    )
    state.db.add(replacement)
    asset.current_version_id = replacement.id
    state.db.flush()
    assert (await library.list_choices(actor, program_id=state.program)).items == ()


async def test_asset_bound_in_multiple_courses_is_returned_once(state):
    library, actor, _ = await access(state)
    asset, version = video(state, owner=state.manager)
    bind(state, asset, version)
    bind(state, asset, version, program=state.second)
    page = await library.list_choices(actor, program_id=state.program)
    assert [item.asset_id for item in page.items] == [asset.id]
    assert page.next_cursor is None


async def test_multiple_qualifying_bindings_in_one_course_do_not_fill_the_page_twice(state):
    library, actor, _ = await access(state)
    asset, version = video(state, owner=state.manager, asset_id=UUID(int=100))
    bind(state, asset, version, status="superseded")
    bind(state, asset, version, version_number=2)
    following, _ = video(state, asset_id=UUID(int=101))
    page = await library.list_choices(
        actor, program_id=state.program, query=StudioVideoLibraryQuery(limit=2)
    )
    assert [item.asset_id for item in page.items] == [asset.id, following.id]
    assert page.next_cursor is None


async def test_intent_timestamp_ties_use_id_and_never_cross_asset_or_version(state):
    library, actor, _ = await access(state)
    asset, original = video(state, asset_id=UUID(int=100))
    now = datetime.now(UTC)
    upload(state, asset, original, "Earlier tie.mp4", now, intent_id=UUID(int=100))
    upload(state, asset, original, "Chosen tie.mp4", now, intent_id=UUID(int=101))
    # Insert the smaller ID last: insertion order must not select the label.
    upload(state, asset, original, "Inserted last.mp4", now, intent_id=UUID(int=99))
    newer = MediaVersion(
        id=uuid4(),
        tenant_id=state.academy,
        asset_id=asset.id,
        version_number=2,
        purpose="video",
        state="processing",
        content_type="video/mp4",
        declared_bytes=2000,
        object_key="test-private/not-current-source",
    )
    state.db.add(newer)
    state.db.flush()
    upload(state, asset, newer, "Wrong version.mp4", now + timedelta(minutes=1))
    another, another_version = video(state, owner=state.manager)
    upload(state, another, another_version, "Other instructor.mp4", now + timedelta(minutes=2))
    page = await library.list_choices(actor, program_id=state.program)
    assert len(page.items) == 1
    assert page.items[0].asset_id == asset.id
    assert page.items[0].version_id == original.id
    assert page.items[0].label == "Chosen tie.mp4"


async def test_corrupt_processed_metadata_returns_a_safe_refresh_error(state):
    library, actor, _ = await access(state)
    _, version = video(state)
    version.width = 0
    state.db.flush()
    with pytest.raises(MediaConflict, match="Refresh the library") as failure:
        await library.list_choices(actor, program_id=state.program)
    assert "test-private" not in str(failure.value)


async def test_page_uses_one_bounded_media_query_and_does_not_expand_to_tenant_private_uploads(
    state,
):
    library, actor, _ = await access(state)
    await assign(state, permission="catalog_write")  # Academy-wide content grant.
    for i in range(1, 5):
        video(state, asset_id=UUID(int=i), owner=state.manager)
    for i in range(100, 105):
        video(state, asset_id=UUID(int=i))
    statements = []
    event.listen(
        state.db.get_bind(),
        "before_cursor_execute",
        lambda _c, _u, sql, *_a: statements.append(sql),
    )
    page = await library.list_choices(
        actor,
        program_id=state.program,
        query=StudioVideoLibraryQuery(limit=2),
    )
    assert [item.asset_id for item in page.items] == [UUID(int=100), UUID(int=101)]
    media_reads = [sql for sql in statements if "media_assets" in sql]
    assert len(media_reads) == 1
    assert "LIMIT" in media_reads[0]
