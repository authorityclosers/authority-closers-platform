"""Audited publication of the one Coach-owned Free Course.

Coach authoring is tenant scoped while the learner catalog is global.  This
module is the deliberately small bridge between those scopes.  It copies one
already published tenant version through the normal catalog application
commands, preserving the source tenant rows and their provenance.  A draft
source may be reviewed in the same caller-owned transaction when the exact
source and release evidence is supplied.  Media is intentionally a separate,
tenant-scoped approval: callers must not infer a cross-tenant media owner from
this catalog command.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import SessionTransactionOrigin

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.authorization.policy import CapabilityDenied
from ac_platform.authorization.studio import StudioAuthorization
from ac_platform.catalog.content import (
    CanonicalActivityContent,
    CanonicalModuleContent,
    canonical_catalog_content_digest,
)
from ac_platform.catalog.models import (
    Activity,
    CatalogScope,
    Module,
    ModulePrerequisite,
    Program,
    ProgramVersion,
    ProgramVersionStatus,
)
from ac_platform.catalog.services import AsyncCatalogApplication
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Tenant, TenantStatus

AUTHORITY_CLOSERS_FREE_COURSE_SLUG = "authority-closers-free-course"
FREE_COURSE_PUBLICATION_ACTION = "catalog.free_course_published.v1"
FREE_COURSE_ADOPTION_ACTION = "catalog.free_course_adopted.v1"
_IDENTITY_NAMESPACE = UUID("a2c87674-1cb2-4c0b-8a7d-3cddc2efbe4a")
_REQUIRED_PLATFORM_CAPABILITIES = frozenset({"platform_catalog_write", "platform_catalog_publish"})
_RELEASE_ID = re.compile(r"^[0-9a-f]{40}$")


class FreeCoursePublicationError(RuntimeError):
    """The one approved Coach-to-global publication command cannot proceed."""


class FreeCoursePublicationConflict(FreeCoursePublicationError):
    """The command or canonical global slug is already bound to another intent."""


@dataclass(frozen=True, slots=True)
class FreeCoursePublicationResult:
    """Stable result returned by one publication command."""

    status: str
    command_id: UUID
    source_program_id: UUID
    source_version_id: UUID
    program_id: UUID
    program_version_id: UUID
    video_activity_id: UUID
    public_tenant_id: UUID
    media_status: str


def _stable_id(kind: str, source_id: UUID) -> UUID:
    return uuid5(_IDENTITY_NAMESPACE, f"{kind}:{source_id}")


def _require_transaction(database: AsyncSession) -> None:
    transaction = database.get_transaction()
    sync_transaction = None if transaction is None else transaction.sync_transaction
    if sync_transaction is None or sync_transaction.origin is not SessionTransactionOrigin.BEGIN:
        raise FreeCoursePublicationError(
            "Free Course publication requires a caller-owned transaction."
        )


def _result_from_audit(
    event: AuditEvent,
    *,
    command_id: UUID,
    source_program_id: UUID,
    public_tenant_id: UUID,
    operations_tenant_id: UUID,
    actor_person_id: UUID,
    expected_action: str,
) -> FreeCoursePublicationResult:
    if (
        event.id != command_id
        or event.tenant_id != operations_tenant_id
        or event.actor_person_id != actor_person_id
        or event.action != expected_action
        or event.resource_type != "global_program"
        or not isinstance(event.payload, dict)
    ):
        raise FreeCoursePublicationConflict("the command ID has another audit meaning")
    payload = event.payload
    required = {
        "source_program_id",
        "source_version_id",
        "program_id",
        "program_version_id",
        "video_activity_id",
        "public_tenant_id",
        "media_status",
    }
    if set(payload) != required:
        raise FreeCoursePublicationConflict("the publication receipt is incomplete")
    try:
        values = {
            name: UUID(str(payload[name]))
            for name in (
                "source_program_id",
                "source_version_id",
                "program_id",
                "program_version_id",
                "video_activity_id",
                "public_tenant_id",
            )
        }
    except (TypeError, ValueError) as error:
        raise FreeCoursePublicationConflict("the publication receipt is malformed") from error
    if (
        values["source_program_id"] != source_program_id
        or values["public_tenant_id"] != public_tenant_id
    ):
        raise FreeCoursePublicationConflict("the command ID has another publication intent")
    media_status = payload["media_status"]
    if not isinstance(media_status, str) or media_status != "pending_public_tenant_media_owner":
        raise FreeCoursePublicationConflict("the publication receipt has an unknown media state")
    return FreeCoursePublicationResult(
        status="replayed",
        command_id=command_id,
        **values,
        media_status=media_status,
    )


class FreeCoursePublicationApplication:
    """Copy exactly one published Coach version into the global learner catalog.

    The command is intentionally catalog-only.  A target media binding is not
    guessed here because media rows are owned by a target-tenant membership;
    the returned state names the explicit prerequisite for the later canonical
    upload/scan/process/bind operation.
    """

    def __init__(
        self,
        database: AsyncSession,
        *,
        operations_tenant_id: UUID,
        public_tenant_id: UUID,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if operations_tenant_id == public_tenant_id:
            raise FreeCoursePublicationError(
                "the public learner tenant must differ from operations"
            )
        self.database = database
        self.operations_tenant_id = operations_tenant_id
        self.public_tenant_id = public_tenant_id
        self.clock = clock or (lambda: datetime.now(UTC))

    async def apply(
        self,
        *,
        actor: ActorContext,
        source_program_id: UUID,
        command_id: UUID,
        reason: str,
        source_ref: str | None = None,
        release_id: str | None = None,
        reviewed_at: datetime | None = None,
    ) -> FreeCoursePublicationResult:
        """Review/publish the source when needed, then publish its global copy."""

        _require_transaction(self.database)
        if type(command_id) is not UUID or command_id.int == 0:
            raise FreeCoursePublicationError("a non-zero command ID is required")
        if actor.tenant_id != self.operations_tenant_id:
            raise FreeCoursePublicationError("the actor must select the operations tenant")
        if type(source_program_id) is not UUID or source_program_id.int == 0:
            raise FreeCoursePublicationError("a source program ID is required")
        if (
            not isinstance(reason, str)
            or not reason.strip()
            or reason != reason.strip()
            or len(reason) > 500
        ):
            raise FreeCoursePublicationError("a bounded publication reason is required")
        if any(ord(character) < 32 or ord(character) == 127 for character in reason):
            raise FreeCoursePublicationError("the publication reason contains a control character")
        if source_ref is not None and (
            not source_ref.strip()
            or source_ref != source_ref.strip()
            or len(source_ref) > 500
            or any(ord(character) < 32 or ord(character) == 127 for character in source_ref)
        ):
            raise FreeCoursePublicationError("the source reference is invalid")
        if release_id is not None and _RELEASE_ID.fullmatch(release_id) is None:
            raise FreeCoursePublicationError("release_id must be a full lowercase Git SHA")
        if reviewed_at is not None and (
            reviewed_at.tzinfo is None or reviewed_at.utcoffset() is None
        ):
            raise FreeCoursePublicationError("reviewed_at must be timezone-aware")

        try:
            from ac_platform.authorization.platform import platform_projection

            platform_permissions = await platform_projection(
                self.database,
                actor,
                operations_tenant_id=self.operations_tenant_id,
            )
        except CapabilityDenied as error:
            raise FreeCoursePublicationError(str(error)) from error
        if not platform_permissions >= _REQUIRED_PLATFORM_CAPABILITIES:
            raise FreeCoursePublicationError(
                "platform catalog write and publish capabilities are required"
            )

        # A replay still requires fresh platform authority, but does not need
        # the source row to remain mutable or even visible after success.
        existing = await self.database.get(AuditEvent, command_id)
        if existing is not None:
            return _result_from_audit(
                existing,
                command_id=command_id,
                source_program_id=source_program_id,
                public_tenant_id=self.public_tenant_id,
                operations_tenant_id=self.operations_tenant_id,
                actor_person_id=actor.person_id,
                expected_action=FREE_COURSE_PUBLICATION_ACTION,
            )

        source_program = await self.database.scalar(
            select(Program)
            .where(
                Program.id == source_program_id,
                Program.scope == CatalogScope.TENANT.value,
                Program.tenant_id == self.operations_tenant_id,
            )
            .with_for_update()
        )
        if source_program is None:
            raise FreeCoursePublicationError("the source course is unavailable")
        try:
            await StudioAuthorization(self.database).require(
                actor, "catalog_publish", program_id=source_program.id
            )
        except CapabilityDenied as error:
            raise FreeCoursePublicationError(
                "the actor lacks publication authority for the source course"
            ) from error

        public_tenant = await self.database.scalar(
            select(Tenant).where(Tenant.id == self.public_tenant_id).with_for_update(read=True)
        )
        if public_tenant is None or public_tenant.status != TenantStatus.ACTIVE.value:
            raise FreeCoursePublicationError("the public learner tenant is unavailable")

        source_version = await self.database.scalar(
            select(ProgramVersion)
            .where(
                ProgramVersion.program_id == source_program.id,
                ProgramVersion.scope == CatalogScope.TENANT.value,
                ProgramVersion.tenant_id == self.operations_tenant_id,
                ProgramVersion.status.in_(
                    (ProgramVersionStatus.DRAFT.value, ProgramVersionStatus.PUBLISHED.value)
                ),
            )
            .order_by(ProgramVersion.version_number.desc())
            .with_for_update()
        )
        if source_version is None:
            raise FreeCoursePublicationError("the source course version is unavailable")

        modules = tuple(
            (
                await self.database.scalars(
                    select(Module)
                    .where(
                        Module.program_version_id == source_version.id,
                        Module.scope == CatalogScope.TENANT.value,
                        Module.tenant_id == self.operations_tenant_id,
                    )
                    .order_by(Module.position.asc())
                )
            ).all()
        )
        if not modules:
            raise FreeCoursePublicationError("the published source has no modules")
        module_ids = {module.id for module in modules}
        activities_by_module: dict[UUID, tuple[Activity, ...]] = {}
        for module in modules:
            activities_by_module[module.id] = tuple(
                (
                    await self.database.scalars(
                        select(Activity)
                        .where(
                            Activity.module_id == module.id,
                            Activity.program_version_id == source_version.id,
                            Activity.scope == CatalogScope.TENANT.value,
                            Activity.tenant_id == self.operations_tenant_id,
                        )
                        .order_by(Activity.position.asc())
                    )
                ).all()
            )
        video_activities = tuple(
            activity
            for activities in activities_by_module.values()
            for activity in activities
            if activity.kind == "VIDEO"
        )
        if len(video_activities) != 1:
            raise FreeCoursePublicationError(
                "the initial Free Course requires exactly one VIDEO activity"
            )

        prerequisites = tuple(
            (
                await self.database.scalars(
                    select(ModulePrerequisite).where(
                        ModulePrerequisite.program_version_id == source_version.id,
                        ModulePrerequisite.scope == CatalogScope.TENANT.value,
                        ModulePrerequisite.tenant_id == self.operations_tenant_id,
                    )
                )
            ).all()
        )
        if any(
            edge.module_id not in module_ids or edge.prerequisite_module_id not in module_ids
            for edge in prerequisites
        ):
            raise FreeCoursePublicationError("the source prerequisite graph is out of scope")

        target_modules = tuple(
            CanonicalModuleContent(
                position=module.position,
                title=module.title,
                prerequisite_positions=tuple(
                    sorted(
                        prerequisite_module.position
                        for prerequisite in prerequisites
                        if prerequisite.module_id == module.id
                        for prerequisite_module in modules
                        if prerequisite_module.id == prerequisite.prerequisite_module_id
                    )
                ),
                activities=tuple(
                    CanonicalActivityContent(
                        position=activity.position,
                        kind=activity.kind,
                        title=activity.title,
                        is_required=activity.is_required,
                        prompt=activity.prompt,
                    )
                    for activity in activities_by_module[module.id]
                ),
            )
            for module in modules
        )
        target_digest = canonical_catalog_content_digest(
            program_slug=AUTHORITY_CLOSERS_FREE_COURSE_SLUG,
            program_title=source_program.title,
            modules=target_modules,
        )
        source_digest = canonical_catalog_content_digest(
            program_slug=source_program.slug,
            program_title=source_program.title,
            modules=target_modules,
        )
        if (
            source_version.content_digest is not None
            and source_version.content_digest != source_digest
        ):
            raise FreeCoursePublicationError(
                "the source content digest does not match its current draft content"
            )

        target_program_id = _stable_id("program", source_program.id)
        target_version_id = _stable_id("version", source_version.id)
        occupied = await self.database.scalar(
            select(Program).where(
                (Program.id == target_program_id)
                | (
                    (Program.scope == CatalogScope.GLOBAL.value)
                    & (Program.slug == AUTHORITY_CLOSERS_FREE_COURSE_SLUG)
                )
            )
        )
        if occupied is not None:
            raise FreeCoursePublicationConflict(
                "the canonical global Free Course identity is already occupied"
            )
        occupied_version = await self.database.scalar(
            select(ProgramVersion).where(ProgramVersion.id == target_version_id)
        )
        if occupied_version is not None:
            raise FreeCoursePublicationConflict(
                "the deterministic global version identity is already occupied"
            )

        source_review_event_id: UUID | None = None
        if source_version.status == ProgramVersionStatus.DRAFT.value:
            if source_ref is None or release_id is None or reviewed_at is None:
                raise FreeCoursePublicationError(
                    "publish requires source_ref, release_id, and reviewed_at review evidence"
                )
            reviewed_at_value = reviewed_at.astimezone(UTC)
            source_version.content_digest = source_digest
            source_version.content_source_ref = source_ref
            source_version.content_reviewed_by = f"person:{actor.person_id}"
            source_version.content_reviewed_at = reviewed_at_value
            source_version.release_id = release_id
            source_version.content_seed_kind = "reviewed"
            await self.database.flush()
        elif source_version.content_seed_kind != "reviewed":
            raise FreeCoursePublicationError(
                "the source version must carry reviewed publication provenance"
            )

        global_actor = ActorContext(
            person_id=actor.person_id,
            session_id=actor.session_id,
            tenant_id=None,
            permissions=frozenset({"catalog_write", "catalog_publish"}),
        )
        catalog = AsyncCatalogApplication(self.database, clock=self.clock)
        if source_version.status == ProgramVersionStatus.DRAFT.value:
            published_source = await catalog.publish_version(
                source_version.id,
                actor=actor,
                tenant_id=self.operations_tenant_id,
                now=self.clock(),
            )
            source_version.content_digest = published_source.content_digest
            source_review_event_id = uuid5(command_id, "source-review")
            await AuditRepository(self.database).append(
                event_id=source_review_event_id,
                tenant_id=self.operations_tenant_id,
                actor_person_id=actor.person_id,
                session_id=actor.session_id,
                action="audit.catalog.version.reviewed.v1",
                resource_type="program_version",
                resource_id=source_version.id,
                payload={
                    "program_id": str(source_program.id),
                    "version_id": str(source_version.id),
                    "content_digest": source_digest,
                    "content_source_ref": source_version.content_source_ref,
                    "content_reviewed_by": source_version.content_reviewed_by,
                    "content_reviewed_at": reviewed_at_value.isoformat(),
                    "release_id": source_version.release_id,
                    "content_seed_kind": source_version.content_seed_kind,
                },
                reason=reason,
                now=self.clock(),
            )
        try:
            target_program = await catalog.create_program(
                actor=global_actor,
                tenant_id=None,
                scope=CatalogScope.GLOBAL,
                slug=AUTHORITY_CLOSERS_FREE_COURSE_SLUG,
                title=source_program.title,
                program_id=target_program_id,
                now=self.clock(),
            )
            target_version = await catalog.create_version(
                target_program.id,
                actor=global_actor,
                tenant_id=None,
                version_number=1,
                version_id=target_version_id,
                content_digest=target_digest,
                content_source_ref=source_version.content_source_ref,
                content_reviewed_by=source_version.content_reviewed_by,
                content_reviewed_at=source_version.content_reviewed_at,
                release_id=source_version.release_id,
                content_seed_kind=source_version.content_seed_kind,
                now=self.clock(),
            )
            target_module_ids: dict[UUID, UUID] = {}
            for source_module in modules:
                target_module = await catalog.add_module(
                    target_version.id,
                    actor=global_actor,
                    tenant_id=None,
                    title=source_module.title,
                    position=source_module.position,
                    module_id=_stable_id("module", source_module.id),
                )
                target_module_ids[source_module.id] = target_module.id
                for source_activity in activities_by_module[source_module.id]:
                    await catalog.add_activity(
                        target_module.id,
                        actor=global_actor,
                        tenant_id=None,
                        kind=source_activity.kind,
                        title=source_activity.title,
                        prompt=source_activity.prompt,
                        position=source_activity.position,
                        activity_id=_stable_id("activity", source_activity.id),
                        is_required=source_activity.is_required,
                    )
            for prerequisite in prerequisites:
                await catalog.add_module_prerequisite(
                    target_module_ids[prerequisite.module_id],
                    target_module_ids[prerequisite.prerequisite_module_id],
                    actor=global_actor,
                    tenant_id=None,
                    prerequisite_id=_stable_id("prerequisite", prerequisite.id),
                )
            published = await catalog.publish_version(
                target_version.id,
                actor=global_actor,
                tenant_id=None,
                now=self.clock(),
            )
        except Exception:
            raise

        media_status = "pending_public_tenant_media_owner"
        payload = {
            "source_program_id": str(source_program.id),
            "source_version_id": str(source_version.id),
            "program_id": str(target_program.id),
            "program_version_id": str(published.id),
            "video_activity_id": str(_stable_id("activity", video_activities[0].id)),
            "public_tenant_id": str(self.public_tenant_id),
            "media_status": media_status,
        }
        audit = await AuditRepository(self.database).append(
            event_id=command_id,
            tenant_id=self.operations_tenant_id,
            actor_person_id=actor.person_id,
            session_id=actor.session_id,
            action=FREE_COURSE_PUBLICATION_ACTION,
            resource_type="global_program",
            resource_id=target_program.id,
            payload=payload,
            reason=reason,
            now=self.clock(),
        )
        if audit.id != command_id:
            raise FreeCoursePublicationError("publication audit receipt was not committed")
        return FreeCoursePublicationResult(
            status="published",
            command_id=command_id,
            source_program_id=source_program.id,
            source_version_id=source_version.id,
            program_id=target_program.id,
            program_version_id=published.id,
            video_activity_id=_stable_id("activity", video_activities[0].id),
            public_tenant_id=self.public_tenant_id,
            media_status=media_status,
        )

    async def adopt_existing(
        self,
        *,
        actor: ActorContext,
        source_program_id: UUID,
        program_id: UUID,
        program_version_id: UUID,
        video_activity_id: UUID,
        command_id: UUID,
        reason: str,
    ) -> FreeCoursePublicationResult:
        """Record adoption of an already matching global Free Course.

        Staging may already contain canonical global rows with identities that
        predate this command. Adoption is a separate audited command: it
        proves the supplied global program/version/video IDs and content match
        the reviewed Coach source, then leaves every catalog row and learner
        progress untouched.
        """

        _require_transaction(self.database)
        if type(command_id) is not UUID or command_id.int == 0:
            raise FreeCoursePublicationError("a non-zero command ID is required")
        if actor.tenant_id != self.operations_tenant_id:
            raise FreeCoursePublicationError("the actor must select the operations tenant")
        if type(source_program_id) is not UUID or source_program_id.int == 0:
            raise FreeCoursePublicationError("a source program ID is required")
        for value, label in (
            (program_id, "existing global program ID"),
            (program_version_id, "existing global version ID"),
            (video_activity_id, "existing global video activity ID"),
        ):
            if type(value) is not UUID or value.int == 0:
                raise FreeCoursePublicationError(f"a non-zero {label} is required")
        if (
            not isinstance(reason, str)
            or not reason.strip()
            or reason != reason.strip()
            or len(reason) > 500
            or any(ord(character) < 32 or ord(character) == 127 for character in reason)
        ):
            raise FreeCoursePublicationError("a bounded publication reason is required")

        try:
            from ac_platform.authorization.platform import platform_projection

            platform_permissions = await platform_projection(
                self.database,
                actor,
                operations_tenant_id=self.operations_tenant_id,
            )
        except CapabilityDenied as error:
            raise FreeCoursePublicationError(str(error)) from error
        if not platform_permissions >= _REQUIRED_PLATFORM_CAPABILITIES:
            raise FreeCoursePublicationError(
                "platform catalog write and publish capabilities are required"
            )

        existing = await self.database.get(AuditEvent, command_id)
        if existing is not None:
            return _result_from_audit(
                existing,
                command_id=command_id,
                source_program_id=source_program_id,
                public_tenant_id=self.public_tenant_id,
                operations_tenant_id=self.operations_tenant_id,
                actor_person_id=actor.person_id,
                expected_action=FREE_COURSE_ADOPTION_ACTION,
            )

        source_program = await self.database.scalar(
            select(Program)
            .where(
                Program.id == source_program_id,
                Program.scope == CatalogScope.TENANT.value,
                Program.tenant_id == self.operations_tenant_id,
            )
            .with_for_update()
        )
        if source_program is None:
            raise FreeCoursePublicationError("the source course is unavailable")
        try:
            await StudioAuthorization(self.database).require(
                actor, "catalog_publish", program_id=source_program.id
            )
        except CapabilityDenied as error:
            raise FreeCoursePublicationError(
                "the actor lacks publication authority for the source course"
            ) from error

        public_tenant = await self.database.scalar(
            select(Tenant).where(Tenant.id == self.public_tenant_id).with_for_update(read=True)
        )
        if public_tenant is None or public_tenant.status != TenantStatus.ACTIVE.value:
            raise FreeCoursePublicationError("the public learner tenant is unavailable")

        source_version = await self.database.scalar(
            select(ProgramVersion)
            .where(
                ProgramVersion.program_id == source_program.id,
                ProgramVersion.scope == CatalogScope.TENANT.value,
                ProgramVersion.tenant_id == self.operations_tenant_id,
                ProgramVersion.status == ProgramVersionStatus.PUBLISHED.value,
            )
            .order_by(ProgramVersion.version_number.desc())
            .with_for_update()
        )
        if source_version is None or source_version.content_seed_kind != "reviewed":
            raise FreeCoursePublicationError(
                "the source version must carry reviewed publication provenance"
            )

        modules = tuple(
            (
                await self.database.scalars(
                    select(Module)
                    .where(
                        Module.program_version_id == source_version.id,
                        Module.scope == CatalogScope.TENANT.value,
                        Module.tenant_id == self.operations_tenant_id,
                    )
                    .order_by(Module.position.asc())
                )
            ).all()
        )
        if not modules:
            raise FreeCoursePublicationError("the published source has no modules")
        module_ids = {module.id for module in modules}
        activities_by_module: dict[UUID, tuple[Activity, ...]] = {}
        for module in modules:
            activities_by_module[module.id] = tuple(
                (
                    await self.database.scalars(
                        select(Activity)
                        .where(
                            Activity.module_id == module.id,
                            Activity.program_version_id == source_version.id,
                            Activity.scope == CatalogScope.TENANT.value,
                            Activity.tenant_id == self.operations_tenant_id,
                        )
                        .order_by(Activity.position.asc())
                    )
                ).all()
            )
        video_activities = tuple(
            activity
            for activities in activities_by_module.values()
            for activity in activities
            if activity.kind == "VIDEO"
        )
        if len(video_activities) != 1:
            raise FreeCoursePublicationError(
                "the initial Free Course requires exactly one VIDEO activity"
            )
        prerequisites = tuple(
            (
                await self.database.scalars(
                    select(ModulePrerequisite).where(
                        ModulePrerequisite.program_version_id == source_version.id,
                        ModulePrerequisite.scope == CatalogScope.TENANT.value,
                        ModulePrerequisite.tenant_id == self.operations_tenant_id,
                    )
                )
            ).all()
        )
        if any(
            edge.module_id not in module_ids or edge.prerequisite_module_id not in module_ids
            for edge in prerequisites
        ):
            raise FreeCoursePublicationError("the source prerequisite graph is out of scope")
        target_modules = tuple(
            CanonicalModuleContent(
                position=module.position,
                title=module.title,
                prerequisite_positions=tuple(
                    sorted(
                        prerequisite_module.position
                        for prerequisite in prerequisites
                        if prerequisite.module_id == module.id
                        for prerequisite_module in modules
                        if prerequisite_module.id == prerequisite.prerequisite_module_id
                    )
                ),
                activities=tuple(
                    CanonicalActivityContent(
                        position=activity.position,
                        kind=activity.kind,
                        title=activity.title,
                        is_required=activity.is_required,
                        prompt=activity.prompt,
                    )
                    for activity in activities_by_module[module.id]
                ),
            )
            for module in modules
        )
        source_digest = canonical_catalog_content_digest(
            program_slug=source_program.slug,
            program_title=source_program.title,
            modules=target_modules,
        )
        target_digest = canonical_catalog_content_digest(
            program_slug=AUTHORITY_CLOSERS_FREE_COURSE_SLUG,
            program_title=source_program.title,
            modules=target_modules,
        )
        if source_version.content_digest != source_digest:
            raise FreeCoursePublicationError(
                "the source content digest does not match its reviewed content"
            )

        target_program = await self.database.scalar(
            select(Program).where(
                Program.id == program_id,
                Program.scope == CatalogScope.GLOBAL.value,
                Program.slug == AUTHORITY_CLOSERS_FREE_COURSE_SLUG,
                Program.tenant_id.is_(None),
                Program.owner_key == UUID(int=0),
            )
        )
        if target_program is None or target_program.title != source_program.title:
            raise FreeCoursePublicationConflict(
                "the existing global Free Course does not match the reviewed source"
            )
        target_version = await self.database.scalar(
            select(ProgramVersion).where(
                ProgramVersion.id == program_version_id,
                ProgramVersion.program_id == program_id,
                ProgramVersion.scope == CatalogScope.GLOBAL.value,
                ProgramVersion.tenant_id.is_(None),
                ProgramVersion.owner_key == UUID(int=0),
                ProgramVersion.status == ProgramVersionStatus.PUBLISHED.value,
            )
        )
        if (
            target_version is None
            or target_version.content_digest != target_digest
            or target_version.content_source_ref != source_version.content_source_ref
            or target_version.content_reviewed_by != source_version.content_reviewed_by
            or target_version.content_reviewed_at != source_version.content_reviewed_at
            or target_version.release_id != source_version.release_id
            or target_version.content_seed_kind != source_version.content_seed_kind
        ):
            raise FreeCoursePublicationConflict(
                "the existing global Free Course version does not match the reviewed source"
            )
        target_activity = await self.database.scalar(
            select(Activity).where(
                Activity.id == video_activity_id,
                Activity.program_id == program_id,
                Activity.program_version_id == program_version_id,
                Activity.scope == CatalogScope.GLOBAL.value,
                Activity.tenant_id.is_(None),
                Activity.owner_key == UUID(int=0),
                Activity.kind == "VIDEO",
            )
        )
        if target_activity is None:
            raise FreeCoursePublicationConflict(
                "the existing global Free Course video activity is unavailable"
            )

        media_status = "pending_public_tenant_media_owner"
        payload = {
            "source_program_id": str(source_program.id),
            "source_version_id": str(source_version.id),
            "program_id": str(target_program.id),
            "program_version_id": str(target_version.id),
            "video_activity_id": str(target_activity.id),
            "public_tenant_id": str(self.public_tenant_id),
            "media_status": media_status,
        }
        audit = await AuditRepository(self.database).append(
            event_id=command_id,
            tenant_id=self.operations_tenant_id,
            actor_person_id=actor.person_id,
            session_id=actor.session_id,
            action=FREE_COURSE_ADOPTION_ACTION,
            resource_type="global_program",
            resource_id=target_program.id,
            payload=payload,
            reason=reason,
            now=self.clock(),
        )
        if audit.id != command_id:
            raise FreeCoursePublicationError("adoption audit receipt was not committed")
        return FreeCoursePublicationResult(
            status="adopted",
            command_id=command_id,
            source_program_id=source_program.id,
            source_version_id=source_version.id,
            program_id=target_program.id,
            program_version_id=target_version.id,
            video_activity_id=target_activity.id,
            public_tenant_id=self.public_tenant_id,
            media_status=media_status,
        )


__all__ = [
    "AUTHORITY_CLOSERS_FREE_COURSE_SLUG",
    "FREE_COURSE_PUBLICATION_ACTION",
    "FREE_COURSE_ADOPTION_ACTION",
    "FreeCoursePublicationApplication",
    "FreeCoursePublicationConflict",
    "FreeCoursePublicationError",
    "FreeCoursePublicationResult",
]
