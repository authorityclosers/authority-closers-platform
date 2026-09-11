"""Post-candidate Studio picker contracts; no runtime route/provider activation."""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from ac_platform.media.models import MediaAsset, MediaUploadIntent, MediaVersion
from ac_platform.media.public_film_manifest import (
    MANIFEST_SHA256 as PUBLIC_DIGEST,
)
from ac_platform.media.public_film_manifest import (
    public_film_media_identity,
)
from ac_platform.media.staging_fixture_manifest import (
    MANIFEST_SHA256 as STAGING_DIGEST,
)
from ac_platform.media.staging_fixture_manifest import (
    fixture_media_identity,
)
from ac_platform.media.studio_contract import (
    StudioVideoChoice,
    StudioVideoSelectionRequest,
    project_studio_video_choice,
)


def selection(**changes: object) -> dict[str, object]:
    return {
        "asset_id": str(uuid4()),
        "version_id": str(uuid4()),
        "expected_binding_id": None,
        "approval_reference": " Reviewed lesson source ",
        **changes,
    }


def rows() -> tuple[UUID, MediaAsset, MediaVersion, MediaUploadIntent]:
    tenant_id, owner_id, asset_id, version_id = (uuid4() for _ in range(4))
    asset = MediaAsset(
        id=asset_id,
        tenant_id=tenant_id,
        owner_person_id=owner_id,
        purpose="video",
        state="ready",
        current_version_id=version_id,
    )
    version = MediaVersion(
        id=version_id,
        tenant_id=tenant_id,
        asset_id=asset_id,
        version_number=2,
        purpose="video",
        state="ready",
        content_type="video/mp4",
        declared_bytes=999999,
        actual_bytes=800000,
        duration_seconds=12.5,
        width=3840,
        height=2160,
        object_key="private-provider-object-do-not-serialize",
        provider_asset_id="private-provider-id-do-not-serialize",
        storage_version_id="private-storage-id-do-not-serialize",
    )
    intent = MediaUploadIntent(
        tenant_id=tenant_id,
        actor_person_id=owner_id,
        asset_id=asset_id,
        version_id=version_id,
        filename="Discovery lesson.mp4",
    )
    return tenant_id, asset, version, intent


def test_selection_accepts_uuid_json_and_explicit_initial_binding() -> None:
    request = StudioVideoSelectionRequest.model_validate(selection())
    assert isinstance(request.asset_id, UUID)
    assert request.expected_binding_id is None
    assert request.approval_reference == "Reviewed lesson source"
    with pytest.raises(ValidationError):
        request.approval_reference = "Changed after validation"


def test_selection_requires_explicit_optimistic_concurrency_expectation() -> None:
    body = selection()
    del body["expected_binding_id"]
    with pytest.raises(ValidationError):
        StudioVideoSelectionRequest.model_validate(body)
    prior = uuid4()
    assert (
        StudioVideoSelectionRequest.model_validate(
            selection(expected_binding_id=str(prior))
        ).expected_binding_id
        == prior
    )


@pytest.mark.parametrize(
    "field",
    [
        "tenant_id",
        "person_id",
        "program_id",
        "program_version_id",
        "module_id",
        "activity_id",
        "program_scope",
        "program_owner_key",
        "activity_version",
        "permissions",
        "url",
        "object_key",
        "provider_asset_id",
        "approved",
        "supersedes_binding_id",
    ],
)
def test_selection_cannot_assert_scope_authority_or_delivery(field: str) -> None:
    with pytest.raises(ValidationError):
        StudioVideoSelectionRequest.model_validate(selection(**{field: "untrusted"}))


@pytest.mark.parametrize("reference", ["", "   ", "a" * 201, "ok\nno", "ok\x00", "a\u202eb"])
def test_selection_rejects_blank_unbounded_or_controlled_approval(reference: str) -> None:
    with pytest.raises(ValidationError):
        StudioVideoSelectionRequest.model_validate(selection(approval_reference=reference))


def test_choice_serializes_only_public_picker_metadata() -> None:
    tenant, asset, version, intent = rows()
    choice = project_studio_video_choice(tenant, asset, version, intent)
    assert choice.model_dump(mode="json") == {
        "asset_id": str(asset.id),
        "version_id": str(version.id),
        "version_number": 2,
        "label": "Discovery lesson.mp4",
        "state": "ready",
        "actual_bytes": 800000,
        "duration_seconds": 12.5,
        "width": 3840,
        "height": 2160,
    }
    assert "private-" not in choice.model_dump_json()
    assert "tenant_id" not in choice.model_dump()
    assert "owner_person_id" not in choice.model_dump()


@pytest.mark.parametrize(
    "target,field,value",
    [
        ("asset", "tenant_id", uuid4()),
        ("version", "tenant_id", uuid4()),
        ("version", "asset_id", uuid4()),
        ("asset", "current_version_id", uuid4()),
        ("asset", "purpose", "avatar"),
        ("version", "purpose", "image"),
        ("asset", "state", "retired"),
        ("asset", "state", "processing"),
        ("version", "state", "processing"),
        ("version", "state", "failed"),
        ("intent", "tenant_id", uuid4()),
        ("intent", "asset_id", uuid4()),
        ("intent", "version_id", uuid4()),
    ],
)
def test_projection_rejects_cross_scope_stale_unready_or_mismatched_rows(
    target: str,
    field: str,
    value: object,
) -> None:
    tenant, asset, version, intent = rows()
    setattr({"asset": asset, "version": version, "intent": intent}[target], field, value)
    with pytest.raises(ValueError, match="unavailable"):
        project_studio_video_choice(tenant, asset, version, intent)


@pytest.mark.parametrize(
    "filename",
    [
        "",
        "  ",
        "../secret.mp4",
        r"C:\private\secret.mp4",
        "https://host/video.mp4",
        "..",
        "bad\x00.mp4",
        "trick\u202e.mp4",
        "x" * 256,
    ],
)
def test_unsafe_legacy_filename_is_not_exposed(filename: str) -> None:
    tenant, asset, version, intent = rows()
    intent.filename = filename
    assert project_studio_video_choice(tenant, asset, version, intent).label == "Video · version 2"


def test_missing_metadata_is_not_filled_from_client_declared_upload_size() -> None:
    tenant, asset, version, _ = rows()
    version.actual_bytes = None
    version.duration_seconds = None
    version.height = None
    choice = project_studio_video_choice(tenant, asset, version)
    assert choice.label == "Video · version 2"
    assert choice.actual_bytes is None
    assert choice.duration_seconds is None
    assert choice.width is None and choice.height is None


@pytest.mark.parametrize(
    "identity,digest",
    [
        (public_film_media_identity, PUBLIC_DIGEST),
        (fixture_media_identity, STAGING_DIGEST),
    ],
)
@pytest.mark.parametrize("film", ["bbb-4k-30-normal", "caminandes-gran-dillama-1080p"])
@pytest.mark.parametrize("reserved", ["asset", "version", "both"])
def test_technical_demonstrations_cannot_be_projected_as_course_choices(
    identity,
    digest: str,
    film: str,
    reserved: str,
) -> None:
    tenant, asset, version, _ = rows()
    reserved_asset, reserved_version = identity(tenant, digest, film)
    if reserved in {"asset", "both"}:
        asset.id = version.asset_id = reserved_asset
    if reserved in {"version", "both"}:
        version.id = asset.current_version_id = reserved_version
    with pytest.raises(ValueError, match="unavailable"):
        project_studio_video_choice(tenant, asset, version)


@pytest.mark.parametrize(
    "field,value",
    [
        ("duration_seconds", float("nan")),
        ("duration_seconds", float("inf")),
        ("duration_seconds", 0),
        ("actual_bytes", -1),
        ("actual_bytes", True),
        ("width", 0),
        ("height", -1),
        ("version_number", 0),
    ],
)
def test_invalid_processed_metadata_is_rejected(field: str, value: object) -> None:
    tenant, asset, version, intent = rows()
    setattr(version, field, value)
    with pytest.raises(ValidationError):
        project_studio_video_choice(tenant, asset, version, intent)


def test_response_cannot_silently_include_delivery_or_authority_fields() -> None:
    tenant, asset, version, intent = rows()
    choice = project_studio_video_choice(tenant, asset, version, intent)
    with pytest.raises(ValidationError):
        StudioVideoChoice.model_validate({**choice.model_dump(), "url": "https://private"})
