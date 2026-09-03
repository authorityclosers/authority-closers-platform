"""Tenant-scoped activity/media binding and learner authorization helpers."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ac_platform.kernel.authz import ActorContext
from ac_platform.media.api_contracts import ActivityMediaBindingResponse
from ac_platform.media.contracts import (
    AuthorizedMediaVersion,
    MediaAssetId,
    MediaAssetVersion,
    MediaVersionId,
    create_media_authorization_context,
)
from ac_platform.media.models import (
    ActivityMediaBinding,
    MediaAsset,
    MediaBindingState,
    MediaLifecycle,
    MediaPurpose,
    MediaVersion,
)


@dataclass(frozen=True, slots=True)
class ActivityMediaBindingSnapshot:
    """Safe projection of one approved binding and its ready media version."""

    binding_id: UUID
    tenant_id: UUID
    activity_id: UUID
    module_id: UUID
    program_version_id: UUID
    program_id: UUID
    program_scope: str
    program_owner_key: UUID
    activity_version: str
    asset_id: UUID
    version_id: UUID
    content_type: str
    duration_seconds: float | None
    width: int | None
    height: int | None

    @property
    def media_asset_id(self) -> UUID:
        return self.asset_id

    @property
    def media_version_id(self) -> UUID:
        return self.version_id

    def as_authorized_media_version(self, actor: ActorContext) -> AuthorizedMediaVersion:
        """Create the opaque adapter input only after learner scope is trusted."""

        if actor.tenant_id != self.tenant_id:
            raise ValueError("activity media binding is outside the actor tenant")
        return AuthorizedMediaVersion(
            authorization=create_media_authorization_context(
                tenant_id=str(self.tenant_id),
                person_id=str(actor.person_id),
                session_id=str(actor.session_id),
            ),
            activity_id=str(self.activity_id),
            activity_version=self.activity_version,
            media_version=MediaAssetVersion(
                asset_id=MediaAssetId(str(self.asset_id)),
                version_id=MediaVersionId(str(self.version_id)),
            ),
        )


def _snapshot(
    binding: ActivityMediaBinding,
    version: MediaVersion,
) -> ActivityMediaBindingSnapshot:
    return ActivityMediaBindingSnapshot(
        binding_id=binding.id,
        tenant_id=binding.tenant_id,
        activity_id=binding.activity_id,
        module_id=binding.module_id,
        program_version_id=binding.program_version_id,
        program_id=binding.program_id,
        program_scope=binding.program_scope,
        program_owner_key=binding.program_owner_key,
        activity_version=binding.activity_version,
        asset_id=binding.asset_id,
        version_id=binding.version_id,
        content_type=version.content_type,
        duration_seconds=version.duration_seconds,
        width=version.width,
        height=version.height,
    )


def resolve_activity_media_binding(
    database: Session,
    *,
    tenant_id: UUID,
    activity_id: UUID,
    module_id: UUID,
    program_version_id: UUID,
    program_id: UUID,
    program_scope: str,
    program_owner_key: UUID,
) -> ActivityMediaBindingSnapshot | None:
    """Resolve only the current approved, ready binding for one full scope.

    The tenant predicate is independent of the catalog scope.  A global
    activity therefore gets a separate decision per learner tenant, while a
    tenant-owned activity must still match the copied catalog owner key.
    """

    row = database.execute(
        select(ActivityMediaBinding, MediaAsset, MediaVersion)
        .join(
            MediaAsset,
            (MediaAsset.tenant_id == ActivityMediaBinding.tenant_id)
            & (MediaAsset.id == ActivityMediaBinding.asset_id),
        )
        .join(
            MediaVersion,
            (MediaVersion.tenant_id == ActivityMediaBinding.tenant_id)
            & (MediaVersion.asset_id == ActivityMediaBinding.asset_id)
            & (MediaVersion.id == ActivityMediaBinding.version_id),
        )
        .where(
            ActivityMediaBinding.tenant_id == tenant_id,
            ActivityMediaBinding.activity_id == activity_id,
            ActivityMediaBinding.module_id == module_id,
            ActivityMediaBinding.program_version_id == program_version_id,
            ActivityMediaBinding.program_id == program_id,
            ActivityMediaBinding.program_scope == program_scope,
            ActivityMediaBinding.program_owner_key == program_owner_key,
            ActivityMediaBinding.state == MediaBindingState.APPROVED.value,
            MediaAsset.purpose == MediaPurpose.VIDEO.value,
            MediaAsset.state != MediaLifecycle.RETIRED.value,
            MediaVersion.purpose == MediaPurpose.VIDEO.value,
            MediaVersion.state == MediaLifecycle.READY.value,
        )
        .order_by(ActivityMediaBinding.approved_at.desc(), ActivityMediaBinding.id.desc())
    ).first()
    if row is None:
        return None
    binding, _asset, version = row
    return _snapshot(binding, version)


def resolve_activity_media_binding_for_learning(
    database: Session,
    tenant_id: UUID,
    catalog_activity: object,
    catalog_version: object,
) -> ActivityMediaBindingSnapshot | None:
    """Adapter callback used by the learning repository.

    It receives catalog rows already selected by the enrolled learning scope;
    all identity values are still repeated in the binding query so a callback
    cannot widen access by activity id alone.
    """

    return resolve_activity_media_binding(
        database,
        tenant_id=tenant_id,
        activity_id=catalog_activity.id,  # type: ignore[attr-defined]
        module_id=catalog_activity.module_id,  # type: ignore[attr-defined]
        program_version_id=catalog_version.id,  # type: ignore[attr-defined]
        program_id=catalog_activity.program_id,  # type: ignore[attr-defined]
        program_scope=catalog_activity.scope,  # type: ignore[attr-defined]
        program_owner_key=catalog_activity.owner_key,  # type: ignore[attr-defined]
    )


def binding_response(binding: ActivityMediaBinding) -> ActivityMediaBindingResponse:
    """Project a binding without exposing object keys or provider ids."""

    return ActivityMediaBindingResponse(
        id=binding.id,
        tenant_id=binding.tenant_id,
        activity_id=binding.activity_id,
        module_id=binding.module_id,
        program_version_id=binding.program_version_id,
        program_id=binding.program_id,
        program_scope=binding.program_scope,  # type: ignore[arg-type]
        program_owner_key=binding.program_owner_key,
        activity_version=binding.activity_version,
        asset_id=binding.asset_id,
        version_id=binding.version_id,
        state=binding.state,  # type: ignore[arg-type]
        approval_reference=binding.approval_reference,
        approved_by_person_id=binding.approved_by_person_id,
        approved_at=binding.approved_at,
        supersedes_binding_id=binding.supersedes_binding_id,
        superseded_at=binding.superseded_at,
        revoked_at=binding.revoked_at,
        created_at=binding.created_at,
        updated_at=binding.updated_at,
    )


__all__ = [
    "ActivityMediaBindingSnapshot",
    "binding_response",
    "resolve_activity_media_binding",
    "resolve_activity_media_binding_for_learning",
]
