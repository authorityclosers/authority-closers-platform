"""Real relational checks for the exact Studio upload-context promotion boundary.

READY asset rows alone are insufficient: promotion must retain one immutable
course admission and its matching completed upload intent. SQLite exercises
the actual joins and constraints here; this is not PostgreSQL lock evidence.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from ac_platform.catalog.free_course_media import (
    FreeCourseMediaPromotionError,
    _require_source_studio_upload,
)
from ac_platform.catalog.models import Program
from ac_platform.media.models import (
    MediaAsset,
    MediaUploadIntent,
    MediaVersion,
    StudioVideoUpload,
)
from ac_platform.tenancy.models import Membership
from tests.unit.authorization.test_capability_application import AwaitableSession
from tests.unit.authorization.test_capability_application import state as state  # noqa: F401


def _add_admission(database, asset, version, *, program_id, actor_id, admitted=True):
    """Completed upload fixture with the same immutable linkage as StudioVideoUploads."""

    intent = MediaUploadIntent(
        id=uuid4(),
        tenant_id=asset.tenant_id,
        actor_person_id=actor_id,
        asset_id=asset.id,
        version_id=version.id,
        object_key=version.object_key,
        filename="approved-test-video.mp4",
        content_type=version.content_type,
        declared_bytes=version.actual_bytes,
        checksum_sha256=version.checksum_sha256,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
        max_bytes=version.actual_bytes,
        state="ready",
        request_fingerprint="a" * 64,
        completion_fingerprint="b" * 64,
    )
    database.add(intent)
    database.flush()
    if admitted:
        database.add(
            StudioVideoUpload(
                upload_id=intent.id,
                tenant_id=asset.tenant_id,
                program_id=program_id,
            )
        )
        database.flush()
    return intent


@pytest.fixture
def source(state):
    program_id, other_program_id = uuid4(), uuid4()
    for program in (program_id, other_program_id):
        state.db.add(
            Program(
                id=program,
                scope="tenant",
                tenant_id=state.operations,
                slug=program.hex,
                title="Explicit Studio upload context",
            )
        )
    state.db.flush()
    asset = MediaAsset(
        id=uuid4(),
        tenant_id=state.operations,
        owner_person_id=state.manager,
        purpose="video",
        state="ready",
    )
    state.db.add(asset)
    state.db.flush()
    version_id = uuid4()
    version = MediaVersion(
        id=version_id,
        tenant_id=state.operations,
        asset_id=asset.id,
        version_number=1,
        purpose="video",
        state="ready",
        content_type="video/mp4",
        declared_bytes=8,
        actual_bytes=8,
        checksum_sha256="c" * 64,
        object_key=f"tenants/{state.operations}/media/video/{asset.id}/{version_id}/original",
        storage_version_id="fixture-object-version",
        duration_seconds=4,
    )
    state.db.add(version)
    state.db.flush()
    asset.current_version_id = version.id
    state.db.flush()
    return SimpleNamespace(
        state=state,
        program=program_id,
        other_program=other_program_id,
        asset=asset,
        version=version,
    )


async def _require(source, **changes):
    arguments = {
        "operations_tenant_id": source.state.operations,
        "source_program_id": source.program,
        "owner_person_id": source.state.manager,
        "source_asset": source.asset,
        "source_version": source.version,
    }
    arguments.update(changes)
    await _require_source_studio_upload(AwaitableSession(source.state.db), **arguments)


async def test_completed_exact_admission_passes_without_mutating_or_requiring_live_upload_url(
    source,
):
    intent = _add_admission(
        source.state.db,
        source.asset,
        source.version,
        program_id=source.program,
        actor_id=source.state.manager,
    )
    before = (intent.state, intent.expires_at, intent.completion_fingerprint)
    await _require(source)
    assert (intent.state, intent.expires_at, intent.completion_fingerprint) == before
    assert not source.state.db.dirty


@pytest.mark.parametrize("admitted", [False, True])
async def test_ready_media_without_exact_source_program_admission_is_refused(source, admitted):
    _add_admission(
        source.state.db,
        source.asset,
        source.version,
        program_id=source.other_program,
        actor_id=source.state.manager,
        admitted=admitted,
    )
    with pytest.raises(FreeCourseMediaPromotionError, match="source Studio upload"):
        await _require(source)


async def test_ambiguous_admissions_are_refused_even_when_one_matches(source):
    for program_id in (source.program, source.other_program):
        _add_admission(
            source.state.db,
            source.asset,
            source.version,
            program_id=program_id,
            actor_id=source.state.manager,
        )
    with pytest.raises(FreeCourseMediaPromotionError, match="provenance is unavailable"):
        await _require(source)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("state", "processing"),
        ("object_key", "another/private/object"),
        ("content_type", "video/webm"),
        ("declared_bytes", 7),
        ("checksum_sha256", "d" * 64),
        ("completion_fingerprint", None),
    ],
)
async def test_intent_must_match_the_completed_ready_version(source, field, value):
    intent = _add_admission(
        source.state.db,
        source.asset,
        source.version,
        program_id=source.program,
        actor_id=source.state.manager,
    )
    setattr(intent, field, value)
    source.state.db.flush()
    with pytest.raises(FreeCourseMediaPromotionError, match="does not match its context"):
        await _require(source)


async def test_intent_owner_must_match_the_authorized_source_owner(source):
    source.state.db.add(
        Membership(
            tenant_id=source.state.operations,
            person_id=source.state.stranger,
            role="learner",
        )
    )
    source.state.db.flush()
    _add_admission(
        source.state.db,
        source.asset,
        source.version,
        program_id=source.program,
        actor_id=source.state.stranger,
    )
    with pytest.raises(FreeCourseMediaPromotionError, match="does not match its context"):
        await _require(source)


async def test_different_operations_tenant_cannot_supply_provenance(source):
    _add_admission(
        source.state.db,
        source.asset,
        source.version,
        program_id=source.program,
        actor_id=source.state.manager,
    )
    with pytest.raises(FreeCourseMediaPromotionError, match="provenance is unavailable"):
        await _require(source, operations_tenant_id=source.state.academy)


async def test_admission_for_another_version_cannot_authorize_ready_bytes(source):
    intent = _add_admission(
        source.state.db,
        source.asset,
        source.version,
        program_id=source.program,
        actor_id=source.state.manager,
    )
    other_version = MediaVersion(
        id=uuid4(),
        tenant_id=source.state.operations,
        asset_id=source.asset.id,
        version_number=2,
        purpose="video",
        state="ready",
        content_type="video/mp4",
        declared_bytes=8,
        actual_bytes=8,
        checksum_sha256=source.version.checksum_sha256,
        object_key=source.version.object_key + "/different",
    )
    source.state.db.add(other_version)
    source.state.db.flush()
    intent.version_id = other_version.id
    source.state.db.flush()
    with pytest.raises(FreeCourseMediaPromotionError, match="provenance is unavailable"):
        await _require(source)
    assert source.state.db.scalar(select(StudioVideoUpload.upload_id)) == intent.id
