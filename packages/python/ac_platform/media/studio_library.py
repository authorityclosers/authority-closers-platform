"""Course-authorized video choices for Studio; not yet installed as an HTTP route.

No uploads, URLs, preview grants or binding mutations are performed. The caller
must resolve a real session and own the transaction, as with other Studio APIs.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.authorization.studio import StudioAuthorization
from ac_platform.catalog.models import ProgramVersion
from ac_platform.kernel.authz import ActorContext
from ac_platform.media.errors import MediaConflict
from ac_platform.media.models import (
    ActivityMediaBinding,
    MediaAsset,
    MediaUploadIntent,
    MediaVersion,
)
from ac_platform.media.public_film_manifest import (
    MANIFEST_SHA256 as PUBLIC_FILM_DIGEST,
)
from ac_platform.media.public_film_manifest import public_film_media_identity
from ac_platform.media.staging_fixture_manifest import (
    MANIFEST_SHA256 as STAGING_FILM_DIGEST,
)
from ac_platform.media.staging_fixture_manifest import fixture_media_identity
from ac_platform.media.studio_contract import StudioVideoChoice, project_studio_video_choice


class StudioVideoLibraryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    limit: int = Field(default=24, strict=True, ge=1, le=50)
    after: UUID | None = None


class StudioVideoLibraryPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[StudioVideoChoice, ...] = Field(max_length=50)
    next_cursor: UUID | None


class StudioVideoLibrary:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    async def list_choices(
        self,
        actor: ActorContext,
        *,
        program_id: UUID,
        query: StudioVideoLibraryQuery | None = None,
    ) -> StudioVideoLibraryPage:
        """Read a bounded picker page after fresh exact-course edit authorization.

        A course grant is not a tenant-wide private media-library grant. Choices
        are the actor's own uploads or videos already approved for this course.
        Keyset cursors select a position only; every page rechecks authorization
        and applies the complete tenant/ownership/course predicates before LIMIT.
        """

        await StudioAuthorization(self.database).require(
            actor, "catalog_write", program_id=program_id
        )
        tenant_id = actor.tenant_id
        assert tenant_id is not None  # require() denies a missing tenant before any media query.
        page = query or StudioVideoLibraryQuery()
        reserved = tuple(
            identity(tenant_id, digest, film)
            for identity, digest in (
                (public_film_media_identity, PUBLIC_FILM_DIGEST),
                (fixture_media_identity, STAGING_FILM_DIGEST),
            )
            for film in ("bbb-4k-30-normal", "caminandes-gran-dillama-1080p")
        )
        approved_in_course = exists(
            select(ActivityMediaBinding.id)
            .join(
                ProgramVersion,
                and_(
                    ProgramVersion.id == ActivityMediaBinding.program_version_id,
                    ProgramVersion.program_id == program_id,
                    ProgramVersion.scope == "tenant",
                    ProgramVersion.tenant_id == tenant_id,
                    ProgramVersion.owner_key == tenant_id,
                    ProgramVersion.status.in_(("published", "superseded")),
                ),
            )
            .where(
                ActivityMediaBinding.tenant_id == tenant_id,
                ActivityMediaBinding.program_id == program_id,
                ActivityMediaBinding.program_scope == "tenant",
                ActivityMediaBinding.program_owner_key == tenant_id,
                ActivityMediaBinding.asset_id == MediaAsset.id,
                ActivityMediaBinding.version_id == MediaVersion.id,
                ActivityMediaBinding.state == "approved",
            )
        )
        latest_intent = (
            select(MediaUploadIntent.id)
            .where(
                MediaUploadIntent.tenant_id == tenant_id,
                MediaUploadIntent.asset_id == MediaAsset.id,
                MediaUploadIntent.version_id == MediaVersion.id,
            )
            .order_by(MediaUploadIntent.created_at.desc(), MediaUploadIntent.id.desc())
            .limit(1)
            .correlate(MediaAsset, MediaVersion)
            .scalar_subquery()
        )
        statement = (
            select(MediaAsset, MediaVersion, MediaUploadIntent)
            .join(
                MediaVersion,
                and_(
                    MediaVersion.id == MediaAsset.current_version_id,
                    MediaVersion.asset_id == MediaAsset.id,
                    MediaVersion.tenant_id == tenant_id,
                ),
            )
            .outerjoin(MediaUploadIntent, MediaUploadIntent.id == latest_intent)
            .where(
                MediaAsset.tenant_id == tenant_id,
                MediaAsset.purpose == "video",
                MediaAsset.state == "ready",
                MediaVersion.purpose == "video",
                MediaVersion.state == "ready",
                MediaAsset.id.not_in(tuple(asset for asset, _ in reserved)),
                MediaVersion.id.not_in(tuple(version for _, version in reserved)),
                or_(MediaAsset.owner_person_id == actor.person_id, approved_in_course),
            )
            .order_by(MediaAsset.id)
            .limit(page.limit + 1)
            .execution_options(populate_existing=True)
        )
        if page.after is not None:
            statement = statement.where(MediaAsset.id > page.after)
        rows = (await self.database.execute(statement)).all()
        selected = rows[: page.limit]
        try:
            choices = tuple(
                project_studio_video_choice(tenant_id, asset, version, intent)
                for asset, version, intent in selected
            )
        except ValueError as error:
            raise MediaConflict(
                "Video details changed. Refresh the library and try again."
            ) from error
        return StudioVideoLibraryPage(
            items=choices,
            next_cursor=choices[-1].asset_id if len(rows) > page.limit else None,
        )
