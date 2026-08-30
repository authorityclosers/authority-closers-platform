"""Domain and application services for catalog authoring and publication.

These services use an explicit persistence port so publication policy is
testable without coupling the domain to a web framework or a SQLAlchemy
session.  The SQLAlchemy models in :mod:`ac_platform.catalog.models` provide
the canonical persistence shape; a later enrollment module can consume the
pinning port without becoming a catalog writer.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol, Self, TypeVar, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransactionOrigin

from ac_platform.catalog.content import (
    CanonicalActivityContent,
    CanonicalModuleContent,
    canonical_catalog_content_digest,
)
from ac_platform.catalog.models import (
    ACTIVITY_PROMPT_MAX_LENGTH,
    GLOBAL_CATALOG_OWNER_KEY,
    Activity,
    ActivityKind,
    CatalogScope,
    LearnerVersionPin,
    Module,
    ModulePrerequisite,
    Program,
    ProgramVersion,
    ProgramVersionStatus,
)
from ac_platform.identity.models import Person, PersonStatus
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership, MembershipStatus, Tenant, TenantStatus

CATALOG_WRITE_PERMISSION = "catalog_write"
CATALOG_PUBLISH_PERMISSION = "catalog_publish"
_CONTENT_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_RELEASE_ID = re.compile(r"^[0-9a-f]{40}$")
_REVIEWED_CONTENT_KIND = "reviewed"
_TECHNICAL_VALIDATION_CONTENT_KIND = "technical-validation"
_T = TypeVar("_T")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _now(value: datetime | None) -> datetime:
    return _as_utc(value or datetime.now(UTC))


def _required_text(value: str, field_name: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise CatalogValidationError(f"{field_name} must not be blank")
    if len(normalized) > maximum:
        raise CatalogValidationError(f"{field_name} must be at most {maximum} characters")
    return normalized


def _optional_text(value: str | None, field_name: str, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CatalogValidationError(f"{field_name} must be a string or null")
    return _required_text(value, field_name, maximum)


def _scope_value(scope: CatalogScope | str | None, tenant_id: UUID | None) -> str:
    if scope is None:
        value = CatalogScope.TENANT.value if tenant_id is not None else CatalogScope.GLOBAL.value
    else:
        try:
            value = CatalogScope(scope).value
        except (TypeError, ValueError) as exc:
            raise CatalogValidationError("scope must be 'global' or 'tenant'") from exc
    if value == CatalogScope.GLOBAL.value and tenant_id is not None:
        raise CatalogValidationError("global catalog records cannot carry a tenant_id")
    if value == CatalogScope.TENANT.value and tenant_id is None:
        raise CatalogValidationError("tenant catalog records require a tenant_id")
    return value


def _owner_key(scope: str, tenant_id: UUID | None) -> UUID:
    if scope == CatalogScope.GLOBAL.value:
        if tenant_id is not None:
            raise CatalogValidationError("global catalog records cannot carry a tenant_id")
        return GLOBAL_CATALOG_OWNER_KEY
    if scope == CatalogScope.TENANT.value and tenant_id is not None:
        return tenant_id
    raise CatalogValidationError("tenant catalog records require a tenant_id")


def _validate_snapshot_scope(scope: str, tenant_id: UUID | None) -> None:
    _owner_key(scope, tenant_id)


def _same_catalog_owner(left: Any, right: Any) -> bool:
    return bool(
        left.scope == right.scope
        and left.tenant_id == right.tenant_id
        and left.owner_key == right.owner_key
    )


def _activity_kind_value(kind: ActivityKind | str) -> str:
    try:
        return ActivityKind(kind).value
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(activity_kind.value for activity_kind in ActivityKind)
        raise InvalidActivityKindError(f"activity kind must be one of: {allowed}") from exc


class CatalogServiceError(Exception):
    """Base exception for expected catalog-domain failures."""


class CatalogNotFoundError(CatalogServiceError):
    """The requested catalog resource does not exist."""


class CatalogAccessDeniedError(CatalogServiceError):
    """The caller's tenant context cannot access the requested resource."""


CatalogTenantAccessDeniedError = CatalogAccessDeniedError


class CatalogValidationError(CatalogServiceError):
    """A catalog command contains invalid domain data."""


class CatalogConflictError(CatalogServiceError):
    """The command conflicts with an existing stable catalog identity."""


class CatalogPublicationProvenanceError(CatalogValidationError):
    """Publication lacks a complete, valid review and release provenance."""


class CatalogContentDigestMismatchError(CatalogValidationError):
    """Stored review digest does not match the locked canonical content."""


class CatalogTransactionRequiredError(CatalogServiceError):
    """A production command was called outside a caller-owned transaction."""


class DraftRequiredError(CatalogServiceError):
    """A mutating authoring command targeted a non-draft version."""


class PublishedVersionImmutableError(DraftRequiredError):
    """Published and superseded catalog content cannot be edited in place."""


class OrderingConflictError(CatalogServiceError):
    """A module or activity position is not deterministic and unique."""


class PrerequisiteConflictError(CatalogServiceError):
    """A prerequisite edge crosses a version, points forward, or cycles."""


class SupersessionRequiredError(CatalogServiceError):
    """A second publication must explicitly identify the prior version."""


class InvalidActivityKindError(CatalogValidationError):
    """The activity kind is outside the exact G1 activity taxonomy."""


class LearnerPinningError(CatalogServiceError):
    """The learner-version pin cannot be created or read."""


class LearnerMembershipRequiredError(LearnerPinningError):
    """A pin needs a verified learner membership in its tenant context."""


@dataclass(frozen=True, slots=True)
class ProgramSnapshot:
    """Persistence-independent stable program identity."""

    id: UUID
    scope: str
    tenant_id: UUID | None
    slug: str
    title: str
    created_at: datetime

    @property
    def owner_key(self) -> UUID:
        return _owner_key(self.scope, self.tenant_id)

    @property
    def scope_owner_key(self) -> UUID:
        return self.owner_key


@dataclass(frozen=True, slots=True)
class ProgramVersionSnapshot:
    """Persistence-independent version lifecycle state."""

    id: UUID
    program_id: UUID
    scope: str
    tenant_id: UUID | None
    version_number: int
    status: str
    supersedes_version_id: UUID | None
    published_at: datetime | None
    superseded_at: datetime | None
    created_at: datetime
    content_digest: str | None = None
    content_source_ref: str | None = None
    content_reviewed_by: str | None = None
    content_reviewed_at: datetime | None = None
    release_id: str | None = None
    content_seed_kind: str | None = None

    @property
    def is_immutable(self) -> bool:
        return self.status in {
            ProgramVersionStatus.PUBLISHED.value,
            ProgramVersionStatus.SUPERSEDED.value,
        }

    @property
    def owner_key(self) -> UUID:
        return _owner_key(self.scope, self.tenant_id)

    @property
    def scope_owner_key(self) -> UUID:
        return self.owner_key


@dataclass(frozen=True, slots=True)
class ModuleSnapshot:
    """Persistence-independent ordered module."""

    id: UUID
    program_version_id: UUID
    program_id: UUID
    scope: str
    tenant_id: UUID | None
    position: int
    title: str

    @property
    def owner_key(self) -> UUID:
        return _owner_key(self.scope, self.tenant_id)


@dataclass(frozen=True, slots=True)
class ActivitySnapshot:
    """Persistence-independent ordered activity."""

    id: UUID
    module_id: UUID
    program_version_id: UUID
    program_id: UUID
    scope: str
    tenant_id: UUID | None
    position: int
    kind: str
    title: str
    is_required: bool
    prompt: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "prompt",
            _optional_text(self.prompt, "prompt", ACTIVITY_PROMPT_MAX_LENGTH),
        )

    @property
    def owner_key(self) -> UUID:
        return _owner_key(self.scope, self.tenant_id)


@dataclass(frozen=True, slots=True)
class ModulePrerequisiteSnapshot:
    """Persistence-independent same-version prerequisite edge."""

    id: UUID
    program_version_id: UUID
    program_id: UUID
    scope: str
    tenant_id: UUID | None
    module_id: UUID
    prerequisite_module_id: UUID

    @property
    def owner_key(self) -> UUID:
        return _owner_key(self.scope, self.tenant_id)


@dataclass(frozen=True, slots=True)
class LearnerVersionPinSnapshot:
    """A learner's selected version, deliberately separate from enrollment."""

    id: UUID
    tenant_id: UUID
    learner_person_id: UUID
    program_id: UUID
    program_scope: str
    program_tenant_id: UUID | None
    program_version_id: UUID
    pinned_at: datetime
    program_owner_key: UUID | None = None

    @property
    def owner_key(self) -> UUID:
        return self.program_owner_key or _owner_key(self.program_scope, self.program_tenant_id)


class CatalogStore(Protocol):
    """Persistence port for catalog commands and queries."""

    def get_program(self, program_id: UUID) -> ProgramSnapshot | None: ...

    def get_program_by_slug(
        self,
        slug: str,
        *,
        scope: str,
        tenant_id: UUID | None,
    ) -> ProgramSnapshot | None: ...

    def save_program(self, program: ProgramSnapshot) -> None: ...

    def get_version(self, version_id: UUID) -> ProgramVersionSnapshot | None: ...

    def list_versions(self, program_id: UUID) -> Sequence[ProgramVersionSnapshot]: ...

    def save_version(self, version: ProgramVersionSnapshot) -> None: ...

    def replace_version(self, version: ProgramVersionSnapshot) -> None: ...

    def get_module(self, module_id: UUID) -> ModuleSnapshot | None: ...

    def list_modules(self, program_version_id: UUID) -> Sequence[ModuleSnapshot]: ...

    def save_module(self, module: ModuleSnapshot) -> None: ...

    def get_activity(self, activity_id: UUID) -> ActivitySnapshot | None: ...

    def list_activities(self, module_id: UUID) -> Sequence[ActivitySnapshot]: ...

    def save_activity(self, activity: ActivitySnapshot) -> None: ...

    def list_prerequisites(self, module_id: UUID) -> Sequence[ModulePrerequisiteSnapshot]: ...

    def list_all_prerequisites(self) -> Sequence[ModulePrerequisiteSnapshot]: ...

    def save_prerequisite(self, prerequisite: ModulePrerequisiteSnapshot) -> None: ...

    def get_pin(
        self,
        tenant_id: UUID,
        learner_person_id: UUID,
        program_id: UUID,
    ) -> LearnerVersionPinSnapshot | None: ...

    def save_pin(self, pin: LearnerVersionPinSnapshot) -> None: ...

    def replace_pin(self, pin: LearnerVersionPinSnapshot) -> None: ...


class InMemoryCatalogStore:
    """Deterministic persistence port used by domain/application tests."""

    def __init__(
        self,
        *,
        programs: Iterable[ProgramSnapshot] = (),
        versions: Iterable[ProgramVersionSnapshot] = (),
        modules: Iterable[ModuleSnapshot] = (),
        activities: Iterable[ActivitySnapshot] = (),
        prerequisites: Iterable[ModulePrerequisiteSnapshot] = (),
        pins: Iterable[LearnerVersionPinSnapshot] = (),
    ) -> None:
        self.programs: dict[UUID, ProgramSnapshot] = {program.id: program for program in programs}
        self.versions: dict[UUID, ProgramVersionSnapshot] = {
            version.id: version for version in versions
        }
        self.modules: dict[UUID, ModuleSnapshot] = {module.id: module for module in modules}
        self.activities: dict[UUID, ActivitySnapshot] = {
            activity.id: activity for activity in activities
        }
        self.prerequisites: dict[UUID, ModulePrerequisiteSnapshot] = {
            prerequisite.id: prerequisite for prerequisite in prerequisites
        }
        self.pins: dict[tuple[UUID, UUID, UUID], LearnerVersionPinSnapshot] = {
            (pin.tenant_id, pin.learner_person_id, pin.program_id): pin for pin in pins
        }

    def get_program(self, program_id: UUID) -> ProgramSnapshot | None:
        return self.programs.get(program_id)

    def get_program_by_slug(
        self,
        slug: str,
        *,
        scope: str,
        tenant_id: UUID | None,
    ) -> ProgramSnapshot | None:
        return next(
            (
                program
                for program in self.programs.values()
                if program.slug == slug
                and program.scope == scope
                and program.tenant_id == tenant_id
            ),
            None,
        )

    def save_program(self, program: ProgramSnapshot) -> None:
        _validate_snapshot_scope(program.scope, program.tenant_id)
        if program.id in self.programs:
            raise CatalogConflictError("program id already exists")
        self.programs[program.id] = program

    def get_version(self, version_id: UUID) -> ProgramVersionSnapshot | None:
        return self.versions.get(version_id)

    def list_versions(self, program_id: UUID) -> Sequence[ProgramVersionSnapshot]:
        return tuple(
            version for version in self.versions.values() if version.program_id == program_id
        )

    def save_version(self, version: ProgramVersionSnapshot) -> None:
        _validate_snapshot_scope(version.scope, version.tenant_id)
        program = self.programs.get(version.program_id)
        if program is None or _same_catalog_owner(version, program) is False:
            raise CatalogConflictError("program version scope does not match its program")
        if version.id in self.versions:
            raise CatalogConflictError("program version id already exists")
        if any(
            existing.program_id == version.program_id
            and existing.version_number == version.version_number
            for existing in self.versions.values()
        ):
            raise CatalogConflictError("program version number already exists")
        self.versions[version.id] = version

    def replace_version(self, version: ProgramVersionSnapshot) -> None:
        if version.id not in self.versions:
            raise CatalogNotFoundError("program version does not exist")
        _validate_snapshot_scope(version.scope, version.tenant_id)
        prior = self.versions[version.id]
        if prior.program_id != version.program_id or prior.owner_key != version.owner_key:
            raise CatalogConflictError("program version identity is immutable")
        if version.status == ProgramVersionStatus.PUBLISHED.value and any(
            existing.id != version.id
            and existing.program_id == version.program_id
            and existing.status == ProgramVersionStatus.PUBLISHED.value
            for existing in self.versions.values()
        ):
            raise CatalogConflictError("a program may have only one current published version")
        self.versions[version.id] = version

    def get_module(self, module_id: UUID) -> ModuleSnapshot | None:
        return self.modules.get(module_id)

    def list_modules(self, program_version_id: UUID) -> Sequence[ModuleSnapshot]:
        return tuple(
            module
            for module in self.modules.values()
            if module.program_version_id == program_version_id
        )

    def save_module(self, module: ModuleSnapshot) -> None:
        _validate_snapshot_scope(module.scope, module.tenant_id)
        version = self.versions.get(module.program_version_id)
        if version is None or not _same_catalog_owner(module, version):
            raise CatalogConflictError("module scope does not match its program version")
        if module.id in self.modules:
            raise CatalogConflictError("module id already exists")
        if any(
            existing.program_version_id == module.program_version_id
            and existing.position == module.position
            for existing in self.modules.values()
        ):
            raise OrderingConflictError("module position already exists in this version")
        self.modules[module.id] = module

    def get_activity(self, activity_id: UUID) -> ActivitySnapshot | None:
        return self.activities.get(activity_id)

    def list_activities(self, module_id: UUID) -> Sequence[ActivitySnapshot]:
        return tuple(
            activity for activity in self.activities.values() if activity.module_id == module_id
        )

    def save_activity(self, activity: ActivitySnapshot) -> None:
        _validate_snapshot_scope(activity.scope, activity.tenant_id)
        module = self.modules.get(activity.module_id)
        if module is None or not _same_catalog_owner(activity, module):
            raise CatalogConflictError("activity scope does not match its module")
        if activity.id in self.activities:
            raise CatalogConflictError("activity id already exists")
        if any(
            existing.module_id == activity.module_id and existing.position == activity.position
            for existing in self.activities.values()
        ):
            raise OrderingConflictError("activity position already exists in this module")
        self.activities[activity.id] = activity

    def list_prerequisites(self, module_id: UUID) -> Sequence[ModulePrerequisiteSnapshot]:
        return tuple(
            prerequisite
            for prerequisite in self.prerequisites.values()
            if prerequisite.module_id == module_id
        )

    def list_all_prerequisites(self) -> Sequence[ModulePrerequisiteSnapshot]:
        return tuple(self.prerequisites.values())

    def save_prerequisite(self, prerequisite: ModulePrerequisiteSnapshot) -> None:
        _validate_snapshot_scope(prerequisite.scope, prerequisite.tenant_id)
        module = self.modules.get(prerequisite.module_id)
        required = self.modules.get(prerequisite.prerequisite_module_id)
        version = self.versions.get(prerequisite.program_version_id)
        if (
            module is None
            or required is None
            or version is None
            or not _same_catalog_owner(prerequisite, version)
            or not _same_catalog_owner(prerequisite, module)
            or not _same_catalog_owner(prerequisite, required)
        ):
            raise CatalogConflictError("prerequisite scope does not match its hierarchy")
        if prerequisite.id in self.prerequisites:
            raise CatalogConflictError("prerequisite id already exists")
        if any(
            existing.module_id == prerequisite.module_id
            and existing.prerequisite_module_id == prerequisite.prerequisite_module_id
            for existing in self.prerequisites.values()
        ):
            raise PrerequisiteConflictError("prerequisite edge already exists")
        self.prerequisites[prerequisite.id] = prerequisite

    def get_pin(
        self,
        tenant_id: UUID,
        learner_person_id: UUID,
        program_id: UUID,
    ) -> LearnerVersionPinSnapshot | None:
        return self.pins.get((tenant_id, learner_person_id, program_id))

    def save_pin(self, pin: LearnerVersionPinSnapshot) -> None:
        program = self.programs.get(pin.program_id)
        version = self.versions.get(pin.program_version_id)
        if program is None or version is None:
            raise CatalogConflictError("learner pin references a missing catalog resource")
        if (
            pin.program_scope != program.scope
            or pin.program_tenant_id != program.tenant_id
            or pin.owner_key != program.owner_key
            or version.program_id != program.id
            or version.owner_key != program.owner_key
            or version.scope != program.scope
            or version.tenant_id != program.tenant_id
            or (
                program.scope == CatalogScope.TENANT.value
                and pin.program_tenant_id != pin.tenant_id
            )
        ):
            raise CatalogConflictError("learner pin scope does not match its catalog resources")
        key = (pin.tenant_id, pin.learner_person_id, pin.program_id)
        if key in self.pins:
            raise CatalogConflictError("learner already has a pin for this program")
        self.pins[key] = pin


def _program_snapshot(row: Program) -> ProgramSnapshot:
    return ProgramSnapshot(
        id=row.id,
        scope=row.scope,
        tenant_id=row.tenant_id,
        slug=row.slug,
        title=row.title,
        created_at=_as_utc(row.created_at),
    )


def _version_snapshot(row: ProgramVersion) -> ProgramVersionSnapshot:
    return ProgramVersionSnapshot(
        id=row.id,
        program_id=row.program_id,
        scope=row.scope,
        tenant_id=row.tenant_id,
        version_number=row.version_number,
        status=row.status,
        supersedes_version_id=row.supersedes_version_id,
        published_at=_as_utc(row.published_at) if row.published_at is not None else None,
        superseded_at=_as_utc(row.superseded_at) if row.superseded_at is not None else None,
        created_at=_as_utc(row.created_at),
        content_digest=row.content_digest,
        content_source_ref=row.content_source_ref,
        content_reviewed_by=row.content_reviewed_by,
        content_reviewed_at=(
            _as_utc(row.content_reviewed_at) if row.content_reviewed_at is not None else None
        ),
        release_id=row.release_id,
        content_seed_kind=row.content_seed_kind,
    )


def _module_snapshot(row: Module) -> ModuleSnapshot:
    return ModuleSnapshot(
        id=row.id,
        program_version_id=row.program_version_id,
        program_id=row.program_id,
        scope=row.scope,
        tenant_id=row.tenant_id,
        position=row.position,
        title=row.title,
    )


def _activity_snapshot(row: Activity) -> ActivitySnapshot:
    return ActivitySnapshot(
        id=row.id,
        module_id=row.module_id,
        program_version_id=row.program_version_id,
        program_id=row.program_id,
        scope=row.scope,
        tenant_id=row.tenant_id,
        position=row.position,
        kind=row.kind,
        title=row.title,
        is_required=row.is_required,
        prompt=row.prompt,
    )


def _prerequisite_snapshot(row: ModulePrerequisite) -> ModulePrerequisiteSnapshot:
    return ModulePrerequisiteSnapshot(
        id=row.id,
        program_version_id=row.program_version_id,
        program_id=row.program_id,
        scope=row.scope,
        tenant_id=row.tenant_id,
        module_id=row.module_id,
        prerequisite_module_id=row.prerequisite_module_id,
    )


def _pin_snapshot(row: LearnerVersionPin) -> LearnerVersionPinSnapshot:
    return LearnerVersionPinSnapshot(
        id=row.id,
        tenant_id=row.tenant_id,
        learner_person_id=row.learner_person_id,
        program_id=row.program_id,
        program_scope=row.program_scope,
        program_tenant_id=row.program_tenant_id,
        program_version_id=row.program_version_id,
        pinned_at=_as_utc(row.pinned_at),
        program_owner_key=row.program_owner_key,
    )


class SqlAlchemyCatalogStore:
    """Durable synchronous catalog adapter used inside a caller-owned UoW."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_program(self, program_id: UUID) -> ProgramSnapshot | None:
        row = self._session.get(Program, program_id)
        return _program_snapshot(row) if row is not None else None

    def get_program_by_slug(
        self,
        slug: str,
        *,
        scope: str,
        tenant_id: UUID | None,
    ) -> ProgramSnapshot | None:
        row = self._session.scalar(
            select(Program).where(
                Program.slug == slug,
                Program.scope == scope,
                Program.tenant_id == tenant_id,
            )
        )
        return _program_snapshot(row) if row is not None else None

    def save_program(self, program: ProgramSnapshot) -> None:
        _validate_snapshot_scope(program.scope, program.tenant_id)
        row = Program(
            id=program.id,
            scope=program.scope,
            owner_key=program.owner_key,
            tenant_id=program.tenant_id,
            slug=program.slug,
            title=program.title,
            created_at=program.created_at,
            updated_at=program.created_at,
        )
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError as exc:
            raise CatalogConflictError("program identity or slug already exists") from exc

    def get_version(self, version_id: UUID) -> ProgramVersionSnapshot | None:
        row = self._session.get(ProgramVersion, version_id)
        return _version_snapshot(row) if row is not None else None

    def list_versions(self, program_id: UUID) -> Sequence[ProgramVersionSnapshot]:
        rows = self._session.scalars(
            select(ProgramVersion)
            .where(ProgramVersion.program_id == program_id)
            .order_by(ProgramVersion.version_number.asc(), ProgramVersion.id.asc())
            .execution_options(populate_existing=True)
        ).all()
        return tuple(_version_snapshot(row) for row in rows)

    def save_version(self, version: ProgramVersionSnapshot) -> None:
        program = self.get_program(version.program_id)
        if program is None or not _same_catalog_owner(version, program):
            raise CatalogConflictError("program version scope does not match its program")
        row = ProgramVersion(
            id=version.id,
            program_id=version.program_id,
            scope=version.scope,
            owner_key=version.owner_key,
            tenant_id=version.tenant_id,
            version_number=version.version_number,
            status=version.status,
            supersedes_version_id=version.supersedes_version_id,
            published_at=version.published_at,
            superseded_at=version.superseded_at,
            content_digest=version.content_digest,
            content_source_ref=version.content_source_ref,
            content_reviewed_by=version.content_reviewed_by,
            content_reviewed_at=version.content_reviewed_at,
            release_id=version.release_id,
            content_seed_kind=version.content_seed_kind,
            created_at=version.created_at,
            updated_at=version.created_at,
        )
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError as exc:
            raise CatalogConflictError("program version identity or number already exists") from exc

    def replace_version(self, version: ProgramVersionSnapshot) -> None:
        row = self._session.get(ProgramVersion, version.id)
        if row is None:
            raise CatalogNotFoundError("program version does not exist")
        if row.program_id != version.program_id or row.owner_key != version.owner_key:
            raise CatalogConflictError("program version identity is immutable")
        row.status = version.status
        row.published_at = version.published_at
        row.superseded_at = version.superseded_at
        try:
            with self._session.begin_nested():
                self._session.flush()
        except IntegrityError as exc:
            raise CatalogConflictError(
                "program may have only one current published version"
            ) from exc

    def lock_for_publication(self, version_id: UUID) -> ProgramVersionSnapshot:
        return _version_snapshot(self._lock_program_and_version(version_id))

    def _lock_program_and_version(self, version_id: UUID) -> ProgramVersion:
        candidate_program_id = self._session.scalar(
            select(ProgramVersion.program_id).where(ProgramVersion.id == version_id)
        )
        if candidate_program_id is None:
            raise CatalogNotFoundError("program version does not exist")
        # The stable program row serializes all publication decisions for one
        # catalog identity. Keep Program -> ProgramVersion ordering everywhere.
        locked_program = self._session.scalar(
            select(Program)
            .where(Program.id == candidate_program_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if locked_program is None:
            raise CatalogConflictError("program version references a missing program")
        locked = self._session.scalar(
            select(ProgramVersion)
            .where(ProgramVersion.id == version_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if locked is None:
            raise CatalogNotFoundError("program version does not exist")
        if locked.program_id != locked_program.id:
            raise CatalogConflictError(
                "program version identity changed while publication locks were acquired"
            )
        return locked

    def publish_version_atomically(
        self,
        version_id: UUID,
        *,
        expected_supersedes_version_id: UUID | None,
        published_at: datetime,
        content_digest: str,
    ) -> ProgramVersionSnapshot:
        candidate = self._session.scalar(
            select(ProgramVersion)
            .where(ProgramVersion.id == version_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if candidate is None:
            raise CatalogNotFoundError("program version does not exist")
        current = self._session.scalar(
            select(ProgramVersion)
            .where(
                ProgramVersion.program_id == candidate.program_id,
                ProgramVersion.status == ProgramVersionStatus.PUBLISHED.value,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if candidate.status != ProgramVersionStatus.DRAFT.value:
            raise PublishedVersionImmutableError(
                "published catalog versions are immutable; create a new version"
            )
        if (current.id if current is not None else None) != expected_supersedes_version_id:
            raise SupersessionRequiredError(
                "the publication target changed; explicitly supersede the current version"
            )
        try:
            with self._session.begin_nested():
                # Release the partial unique "current published" slot before
                # publishing the candidate. SQLAlchemy orders a multi-row
                # UPDATE by primary key, which is not the required semantic
                # order when the candidate UUID sorts before the current UUID.
                if current is not None:
                    current.status = ProgramVersionStatus.SUPERSEDED.value
                    current.superseded_at = published_at
                    self._session.flush([current])
                candidate.content_digest = content_digest
                candidate.status = ProgramVersionStatus.PUBLISHED.value
                candidate.published_at = published_at
                self._session.flush([candidate])
        except IntegrityError as exc:
            raise CatalogConflictError(
                "publication violated the current-version invariant"
            ) from exc
        return _version_snapshot(candidate)

    def get_module(self, module_id: UUID) -> ModuleSnapshot | None:
        row = self._session.get(Module, module_id)
        return _module_snapshot(row) if row is not None else None

    def list_modules(self, program_version_id: UUID) -> Sequence[ModuleSnapshot]:
        rows = self._session.scalars(
            select(Module)
            .where(Module.program_version_id == program_version_id)
            .order_by(Module.position.asc(), Module.id.asc())
            .execution_options(populate_existing=True)
        ).all()
        return tuple(_module_snapshot(row) for row in rows)

    def save_module(self, module: ModuleSnapshot) -> None:
        self._lock_draft_version_for_authoring(module.program_version_id)
        row = Module(
            id=module.id,
            program_version_id=module.program_version_id,
            program_id=module.program_id,
            scope=module.scope,
            owner_key=module.owner_key,
            tenant_id=module.tenant_id,
            position=module.position,
            title=module.title,
        )
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError as exc:
            raise OrderingConflictError("module identity or position already exists") from exc

    def get_activity(self, activity_id: UUID) -> ActivitySnapshot | None:
        row = self._session.get(Activity, activity_id)
        return _activity_snapshot(row) if row is not None else None

    def list_activities(self, module_id: UUID) -> Sequence[ActivitySnapshot]:
        rows = self._session.scalars(
            select(Activity)
            .where(Activity.module_id == module_id)
            .order_by(Activity.position.asc(), Activity.id.asc())
            .execution_options(populate_existing=True)
        ).all()
        return tuple(_activity_snapshot(row) for row in rows)

    def save_activity(self, activity: ActivitySnapshot) -> None:
        module = self._session.get(Module, activity.module_id)
        if module is None:
            raise CatalogNotFoundError("module does not exist")
        self._lock_draft_version_for_authoring(module.program_version_id)
        row = Activity(
            id=activity.id,
            module_id=activity.module_id,
            program_version_id=activity.program_version_id,
            program_id=activity.program_id,
            scope=activity.scope,
            owner_key=activity.owner_key,
            tenant_id=activity.tenant_id,
            position=activity.position,
            kind=activity.kind,
            title=activity.title,
            is_required=activity.is_required,
            prompt=activity.prompt,
        )
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError as exc:
            raise OrderingConflictError("activity identity or position already exists") from exc

    def list_prerequisites(self, module_id: UUID) -> Sequence[ModulePrerequisiteSnapshot]:
        rows = self._session.scalars(
            select(ModulePrerequisite).where(ModulePrerequisite.module_id == module_id)
        ).all()
        return tuple(_prerequisite_snapshot(row) for row in rows)

    def list_all_prerequisites(self) -> Sequence[ModulePrerequisiteSnapshot]:
        rows = self._session.scalars(
            select(ModulePrerequisite).execution_options(populate_existing=True)
        ).all()
        return tuple(_prerequisite_snapshot(row) for row in rows)

    def save_prerequisite(self, prerequisite: ModulePrerequisiteSnapshot) -> None:
        self._lock_draft_version_for_authoring(prerequisite.program_version_id)
        row = ModulePrerequisite(
            id=prerequisite.id,
            program_version_id=prerequisite.program_version_id,
            program_id=prerequisite.program_id,
            scope=prerequisite.scope,
            owner_key=prerequisite.owner_key,
            tenant_id=prerequisite.tenant_id,
            module_id=prerequisite.module_id,
            prerequisite_module_id=prerequisite.prerequisite_module_id,
        )
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError as exc:
            raise PrerequisiteConflictError("prerequisite edge already exists") from exc

    def get_pin(
        self,
        tenant_id: UUID,
        learner_person_id: UUID,
        program_id: UUID,
    ) -> LearnerVersionPinSnapshot | None:
        row = self._session.scalar(
            select(LearnerVersionPin).where(
                LearnerVersionPin.tenant_id == tenant_id,
                LearnerVersionPin.learner_person_id == learner_person_id,
                LearnerVersionPin.program_id == program_id,
            )
        )
        return _pin_snapshot(row) if row is not None else None

    def save_pin(self, pin: LearnerVersionPinSnapshot) -> None:
        row = LearnerVersionPin(
            id=pin.id,
            tenant_id=pin.tenant_id,
            learner_person_id=pin.learner_person_id,
            program_id=pin.program_id,
            program_scope=pin.program_scope,
            program_tenant_id=pin.program_tenant_id,
            program_owner_key=pin.owner_key,
            program_version_id=pin.program_version_id,
            pinned_at=pin.pinned_at,
            updated_at=pin.pinned_at,
        )
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError as exc:
            raise CatalogConflictError("learner pin violates its scope or already exists") from exc

    def replace_pin(self, pin: LearnerVersionPinSnapshot) -> None:
        row = self._session.get(LearnerVersionPin, pin.id)
        if row is None:
            raise CatalogNotFoundError("learner pin does not exist")
        row.program_id = pin.program_id
        row.program_scope = pin.program_scope
        row.program_tenant_id = pin.program_tenant_id
        row.program_owner_key = pin.owner_key
        row.program_version_id = pin.program_version_id
        row.pinned_at = pin.pinned_at
        try:
            with self._session.begin_nested():
                self._session.flush()
        except IntegrityError as exc:
            raise CatalogConflictError("learner pin violates its scope") from exc

    def has_active_membership(self, learner_person_id: UUID, tenant_id: UUID) -> bool:
        from ac_platform.tenancy.models import Membership, Tenant

        return (
            self._session.scalar(
                select(Membership.person_id)
                .join(Tenant, Tenant.id == Membership.tenant_id)
                .where(
                    Membership.person_id == learner_person_id,
                    Membership.tenant_id == tenant_id,
                    Membership.role == "learner",
                    Membership.status == "active",
                    Tenant.status == "active",
                )
            )
            is not None
        )

    def _lock_draft_version_for_authoring(self, version_id: UUID) -> ProgramVersion:
        row = self._lock_program_and_version(version_id)
        if row.status != ProgramVersionStatus.DRAFT.value:
            raise PublishedVersionImmutableError(
                "published catalog versions are immutable; create a new version"
            )
        return row


class SqlAlchemyCatalogUnitOfWork:
    """Catalog persistence boundary over one caller-owned AsyncSession."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._committed = False

    async def __aenter__(self) -> Self:
        transaction = self.session.get_transaction()
        sync_transaction = None if transaction is None else transaction.sync_transaction
        if (
            sync_transaction is None
            or sync_transaction.origin is not SessionTransactionOrigin.BEGIN
        ):
            raise CatalogTransactionRequiredError(
                "catalog commands require an explicit caller-owned AsyncSession transaction"
            )
        return self

    async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        del exc_type, exc_value, traceback

    async def run_sync(self, operation: Callable[[Session], _T]) -> _T:
        return await self.session.run_sync(operation)

    async def commit(self) -> None:
        await self.session.flush()
        self._committed = True

    async def rollback(self) -> None:
        self._committed = False


class CatalogService:
    """Author, order, publish, and query the versioned catalog."""

    def __init__(
        self,
        store: CatalogStore,
        *,
        clock: Callable[[], datetime] | None = None,
        allow_technical_validation_publication: bool = False,
    ) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(UTC))
        self._allow_technical_validation_publication = allow_technical_validation_publication

    def create_program(
        self,
        *,
        tenant_id: UUID | None,
        slug: str,
        title: str,
        scope: CatalogScope | str | None = None,
        program_id: UUID | None = None,
        now: datetime | None = None,
    ) -> ProgramSnapshot:
        scope_value = _scope_value(scope, tenant_id)
        normalized_slug = _required_text(slug, "slug", 120)
        normalized_title = _required_text(title, "title", 200)
        if (
            self._store.get_program_by_slug(
                normalized_slug,
                scope=scope_value,
                tenant_id=tenant_id,
            )
            is not None
        ):
            raise CatalogConflictError("program slug already exists in this catalog scope")
        program = ProgramSnapshot(
            id=program_id or uuid4(),
            scope=scope_value,
            tenant_id=tenant_id,
            slug=normalized_slug,
            title=normalized_title,
            created_at=_now(now or self._clock()),
        )
        self._store.save_program(program)
        return program

    def get_program(self, program_id: UUID, *, tenant_id: UUID | None) -> ProgramSnapshot:
        program = self._store.get_program(program_id)
        if program is None:
            raise CatalogNotFoundError("program does not exist")
        self._require_scope_access(program.scope, program.tenant_id, tenant_id)
        return program

    def create_version(
        self,
        program_id: UUID,
        *,
        tenant_id: UUID | None,
        version_number: int | None = None,
        supersedes_version_id: UUID | None = None,
        version_id: UUID | None = None,
        content_digest: str | None = None,
        content_source_ref: str | None = None,
        content_reviewed_by: str | None = None,
        content_reviewed_at: datetime | None = None,
        release_id: str | None = None,
        content_seed_kind: str | None = None,
        now: datetime | None = None,
    ) -> ProgramVersionSnapshot:
        program = self.get_program(program_id, tenant_id=tenant_id)
        self._require_scope_access(program.scope, program.tenant_id, tenant_id, writing=True)
        versions = tuple(self._store.list_versions(program.id))
        number = (
            max((version.version_number for version in versions), default=0) + 1
            if version_number is None
            else version_number
        )
        if number <= 0:
            raise CatalogValidationError("version_number must be positive")
        if any(version.version_number == number for version in versions):
            raise CatalogConflictError("program version number already exists")
        if supersedes_version_id is not None:
            prior = self._require_version(
                supersedes_version_id,
                tenant_id=tenant_id,
                writing=False,
            )
            if (
                prior.program_id != program.id
                or prior.status != ProgramVersionStatus.PUBLISHED.value
            ):
                raise SupersessionRequiredError(
                    "a superseding version must identify the current published version"
                )
            if number <= prior.version_number:
                raise CatalogValidationError("superseding version_number must increase")
        version = ProgramVersionSnapshot(
            id=version_id or uuid4(),
            program_id=program.id,
            scope=program.scope,
            tenant_id=program.tenant_id,
            version_number=number,
            status=ProgramVersionStatus.DRAFT.value,
            supersedes_version_id=supersedes_version_id,
            published_at=None,
            superseded_at=None,
            created_at=_now(now or self._clock()),
            content_digest=content_digest,
            content_source_ref=content_source_ref,
            content_reviewed_by=content_reviewed_by,
            content_reviewed_at=content_reviewed_at,
            release_id=release_id,
            content_seed_kind=content_seed_kind,
        )
        self._store.save_version(version)
        return version

    def create_program_version(self, *args: object, **kwargs: object) -> ProgramVersionSnapshot:
        """Vocabulary alias for :meth:`create_version`."""

        return self.create_version(*args, **kwargs)  # type: ignore[arg-type]

    def add_module(
        self,
        program_version_id: UUID,
        *,
        tenant_id: UUID | None,
        title: str,
        position: int | None = None,
        module_id: UUID | None = None,
    ) -> ModuleSnapshot:
        version = self._require_version(program_version_id, tenant_id=tenant_id, writing=True)
        self._require_draft(version)
        normalized_title = _required_text(title, "title", 200)
        modules = tuple(self._store.list_modules(version.id))
        next_position = (
            max((module.position for module in modules), default=0) + 1
            if position is None
            else position
        )
        self._require_position(next_position, "module")
        if any(module.position == next_position for module in modules):
            raise OrderingConflictError("module position already exists in this version")
        module = ModuleSnapshot(
            id=module_id or uuid4(),
            program_version_id=version.id,
            program_id=version.program_id,
            scope=version.scope,
            tenant_id=version.tenant_id,
            position=next_position,
            title=normalized_title,
        )
        self._store.save_module(module)
        return module

    def create_module(self, *args: object, **kwargs: object) -> ModuleSnapshot:
        """Vocabulary alias for :meth:`add_module`."""

        return self.add_module(*args, **kwargs)  # type: ignore[arg-type]

    def add_activity(
        self,
        module_id: UUID,
        *,
        tenant_id: UUID | None,
        kind: ActivityKind | str,
        title: str,
        prompt: str | None = None,
        position: int | None = None,
        activity_id: UUID | None = None,
        program_version_id: UUID | None = None,
        is_required: bool = True,
    ) -> ActivitySnapshot:
        module = self._require_module(module_id, tenant_id=tenant_id, writing=True)
        version = self._require_version(
            module.program_version_id, tenant_id=tenant_id, writing=True
        )
        self._require_draft(version)
        if program_version_id is not None and program_version_id != version.id:
            raise CatalogAccessDeniedError("activity version does not match its module")
        normalized_title = _required_text(title, "title", 240)
        normalized_prompt = _optional_text(prompt, "prompt", ACTIVITY_PROMPT_MAX_LENGTH)
        kind_value = _activity_kind_value(kind)
        activities = tuple(self._store.list_activities(module.id))
        next_position = (
            max((activity.position for activity in activities), default=0) + 1
            if position is None
            else position
        )
        self._require_position(next_position, "activity")
        if any(activity.position == next_position for activity in activities):
            raise OrderingConflictError("activity position already exists in this module")
        activity = ActivitySnapshot(
            id=activity_id or uuid4(),
            module_id=module.id,
            program_version_id=version.id,
            program_id=version.program_id,
            scope=version.scope,
            tenant_id=version.tenant_id,
            position=next_position,
            kind=kind_value,
            title=normalized_title,
            is_required=is_required,
            prompt=normalized_prompt,
        )
        self._store.save_activity(activity)
        return activity

    def create_activity(self, *args: object, **kwargs: object) -> ActivitySnapshot:
        """Vocabulary alias for :meth:`add_activity`."""

        return self.add_activity(*args, **kwargs)  # type: ignore[arg-type]

    def add_module_prerequisite(
        self,
        module_id: UUID,
        prerequisite_module_id: UUID,
        *,
        tenant_id: UUID | None,
        prerequisite_id: UUID | None = None,
    ) -> ModulePrerequisiteSnapshot:
        module = self._require_module(module_id, tenant_id=tenant_id, writing=True)
        prerequisite = self._require_module(
            prerequisite_module_id,
            tenant_id=tenant_id,
            writing=True,
        )
        version = self._require_version(
            module.program_version_id, tenant_id=tenant_id, writing=True
        )
        self._require_draft(version)
        if prerequisite.program_version_id != module.program_version_id:
            raise PrerequisiteConflictError("prerequisites must belong to the same program version")
        if prerequisite.position >= module.position:
            raise PrerequisiteConflictError(
                "a prerequisite must appear before its dependent module"
            )
        if any(
            existing.module_id == module.id and existing.prerequisite_module_id == prerequisite.id
            for existing in self._all_prerequisites()
        ):
            raise PrerequisiteConflictError("prerequisite edge already exists")
        if self._would_cycle(module.id, prerequisite.id, version.id):
            raise PrerequisiteConflictError("module prerequisites must remain acyclic")
        edge = ModulePrerequisiteSnapshot(
            id=prerequisite_id or uuid4(),
            program_version_id=version.id,
            program_id=version.program_id,
            scope=version.scope,
            tenant_id=version.tenant_id,
            module_id=module.id,
            prerequisite_module_id=prerequisite.id,
        )
        self._store.save_prerequisite(edge)
        return edge

    def add_prerequisite(self, *args: object, **kwargs: object) -> ModulePrerequisiteSnapshot:
        """Vocabulary alias for :meth:`add_module_prerequisite`."""

        return self.add_module_prerequisite(*args, **kwargs)  # type: ignore[arg-type]

    def publish_version(
        self,
        program_version_id: UUID,
        *,
        tenant_id: UUID | None,
        now: datetime | None = None,
    ) -> ProgramVersionSnapshot:
        lock_for_publication = getattr(self._store, "lock_for_publication", None)
        if callable(lock_for_publication):
            version = cast(ProgramVersionSnapshot, lock_for_publication(program_version_id))
            self._require_scope_access(version.scope, version.tenant_id, tenant_id, writing=True)
        else:
            version = self._require_version(program_version_id, tenant_id=tenant_id, writing=True)
        self._require_draft(version)
        self._validate_structure(version)
        self._validate_publication_provenance(version)
        canonical_digest = self._canonical_content_digest(version)
        if version.content_digest != canonical_digest:
            raise CatalogContentDigestMismatchError(
                "content_digest does not match the locked canonical catalog content"
            )
        versions = tuple(self._store.list_versions(version.program_id))
        current = max(
            (
                candidate
                for candidate in versions
                if candidate.status == ProgramVersionStatus.PUBLISHED.value
            ),
            key=lambda candidate: candidate.version_number,
            default=None,
        )
        if current is not None and version.supersedes_version_id != current.id:
            raise SupersessionRequiredError(
                "publish a new version that explicitly supersedes the current published version"
            )
        if current is None and version.supersedes_version_id is not None:
            raise SupersessionRequiredError("the superseded version is not the current publication")
        published_at = _now(now or self._clock())
        publish_atomically = getattr(self._store, "publish_version_atomically", None)
        if callable(publish_atomically):
            return cast(
                ProgramVersionSnapshot,
                publish_atomically(
                    version.id,
                    expected_supersedes_version_id=current.id if current is not None else None,
                    published_at=published_at,
                    content_digest=canonical_digest,
                ),
            )
        published = replace(
            version,
            status=ProgramVersionStatus.PUBLISHED.value,
            published_at=published_at,
            content_digest=canonical_digest,
        )
        if current is not None:
            self._store.replace_version(
                replace(
                    current,
                    status=ProgramVersionStatus.SUPERSEDED.value,
                    superseded_at=published_at,
                )
            )
        self._store.replace_version(published)
        return published

    def publish(self, *args: object, **kwargs: object) -> ProgramVersionSnapshot:
        """Vocabulary alias for :meth:`publish_version`."""

        return self.publish_version(*args, **kwargs)  # type: ignore[arg-type]

    def supersede_version(
        self,
        prior_version_id: UUID,
        *,
        tenant_id: UUID | None,
        version_number: int | None = None,
        version_id: UUID | None = None,
        content_digest: str | None = None,
        content_source_ref: str | None = None,
        content_reviewed_by: str | None = None,
        content_reviewed_at: datetime | None = None,
        release_id: str | None = None,
        content_seed_kind: str | None = None,
        now: datetime | None = None,
    ) -> ProgramVersionSnapshot:
        prior = self._require_version(prior_version_id, tenant_id=tenant_id, writing=False)
        if prior.status != ProgramVersionStatus.PUBLISHED.value:
            raise SupersessionRequiredError("only the current published version can be superseded")
        return self.create_version(
            prior.program_id,
            tenant_id=tenant_id,
            version_number=version_number,
            supersedes_version_id=prior.id,
            version_id=version_id,
            content_digest=content_digest,
            content_source_ref=content_source_ref,
            content_reviewed_by=content_reviewed_by,
            content_reviewed_at=content_reviewed_at,
            release_id=release_id,
            content_seed_kind=content_seed_kind,
            now=now,
        )

    def get_version(
        self,
        program_version_id: UUID,
        *,
        tenant_id: UUID | None,
        published_only: bool = False,
    ) -> ProgramVersionSnapshot:
        version = self._require_version(program_version_id, tenant_id=tenant_id, writing=False)
        if published_only and not version.is_immutable:
            raise CatalogAccessDeniedError("only published catalog versions are readable")
        return version

    def get_published_version(
        self,
        program_id: UUID,
        *,
        tenant_id: UUID | None,
    ) -> ProgramVersionSnapshot:
        self.get_program(program_id, tenant_id=tenant_id)
        current = max(
            (
                version
                for version in self._store.list_versions(program_id)
                if version.status == ProgramVersionStatus.PUBLISHED.value
            ),
            key=lambda version: version.version_number,
            default=None,
        )
        if current is None:
            raise CatalogNotFoundError("program has no current published version")
        self._require_scope_access(current.scope, current.tenant_id, tenant_id)
        return current

    def ordered_modules(
        self,
        program_version_id: UUID,
        *,
        tenant_id: UUID | None,
        published_only: bool = False,
    ) -> tuple[ModuleSnapshot, ...]:
        version = self.get_version(
            program_version_id,
            tenant_id=tenant_id,
            published_only=published_only,
        )
        return tuple(
            sorted(
                self._store.list_modules(version.id),
                key=lambda module: (module.position, module.id.hex),
            )
        )

    def ordered_activities(
        self,
        module_id: UUID,
        *,
        tenant_id: UUID | None,
        published_only: bool = False,
    ) -> tuple[ActivitySnapshot, ...]:
        module = self._require_module(module_id, tenant_id=tenant_id, writing=False)
        version = self.get_version(
            module.program_version_id,
            tenant_id=tenant_id,
            published_only=published_only,
        )
        del version
        return tuple(
            sorted(
                self._store.list_activities(module.id),
                key=lambda activity: (activity.position, activity.id.hex),
            )
        )

    def ordered_prerequisites(
        self,
        module_id: UUID,
        *,
        tenant_id: UUID | None,
        published_only: bool = False,
    ) -> tuple[ModulePrerequisiteSnapshot, ...]:
        module = self._require_module(module_id, tenant_id=tenant_id, writing=False)
        version = self.get_version(
            module.program_version_id,
            tenant_id=tenant_id,
            published_only=published_only,
        )
        del version
        all_edges = tuple(
            edge
            for edge in self._all_prerequisites()
            if edge.module_id == module.id and edge.program_version_id == module.program_version_id
        )
        modules = {
            candidate.id: candidate
            for candidate in self._store.list_modules(module.program_version_id)
        }
        return tuple(
            sorted(
                all_edges,
                key=lambda edge: (
                    modules[edge.prerequisite_module_id].position,
                    edge.prerequisite_module_id.hex,
                ),
            )
        )

    def _require_version(
        self,
        version_id: UUID,
        *,
        tenant_id: UUID | None,
        writing: bool,
    ) -> ProgramVersionSnapshot:
        version = self._store.get_version(version_id)
        if version is None:
            raise CatalogNotFoundError("program version does not exist")
        program = self._store.get_program(version.program_id)
        if program is None:
            raise CatalogConflictError("program version references a missing program")
        if (
            version.scope != program.scope
            or version.tenant_id != program.tenant_id
            or (version.scope == CatalogScope.GLOBAL.value and version.tenant_id is not None)
            or (version.scope == CatalogScope.TENANT.value and version.tenant_id is None)
        ):
            raise CatalogConflictError("program version scope does not match its program")
        self._require_scope_access(version.scope, version.tenant_id, tenant_id, writing=writing)
        return version

    def _require_module(
        self,
        module_id: UUID,
        *,
        tenant_id: UUID | None,
        writing: bool,
    ) -> ModuleSnapshot:
        module = self._store.get_module(module_id)
        if module is None:
            raise CatalogNotFoundError("module does not exist")
        version = self._require_version(
            module.program_version_id, tenant_id=tenant_id, writing=writing
        )
        if (
            module.program_id != version.program_id
            or module.scope != version.scope
            or module.tenant_id != version.tenant_id
        ):
            raise CatalogConflictError("module scope does not match its program version")
        return module

    def _require_draft(self, version: ProgramVersionSnapshot) -> None:
        if version.status != ProgramVersionStatus.DRAFT.value:
            raise PublishedVersionImmutableError(
                "published catalog versions are immutable; create a new version"
            )

    @staticmethod
    def _require_scope_access(
        scope: str,
        resource_tenant_id: UUID | None,
        requested_tenant_id: UUID | None,
        *,
        writing: bool = False,
    ) -> None:
        if scope == CatalogScope.GLOBAL.value:
            if resource_tenant_id is not None:
                raise CatalogConflictError("global catalog resource has an unexpected tenant")
            if writing and requested_tenant_id is not None:
                raise CatalogAccessDeniedError("global catalog authoring requires global context")
            return
        if scope != CatalogScope.TENANT.value:
            raise CatalogConflictError("catalog resource has an unsupported scope")
        if resource_tenant_id is None or requested_tenant_id != resource_tenant_id:
            raise CatalogAccessDeniedError("catalog resource belongs to another tenant")

    @staticmethod
    def _require_position(position: int, resource_name: str) -> None:
        if position <= 0:
            raise OrderingConflictError(f"{resource_name} position must be positive")

    def _validate_structure(self, version: ProgramVersionSnapshot) -> None:
        modules = tuple(self._store.list_modules(version.id))
        module_positions = [module.position for module in modules]
        if any(position <= 0 for position in module_positions) or len(module_positions) != len(
            set(module_positions)
        ):
            raise OrderingConflictError("module positions must be positive and unique")
        module_ids = {module.id for module in modules}
        for module in modules:
            if (
                module.program_id != version.program_id
                or module.scope != version.scope
                or module.tenant_id != version.tenant_id
            ):
                raise CatalogConflictError("module scope does not match its version")
            activities = tuple(self._store.list_activities(module.id))
            activity_positions = [activity.position for activity in activities]
            if any(position <= 0 for position in activity_positions) or len(
                activity_positions
            ) != len(set(activity_positions)):
                raise OrderingConflictError("activity positions must be positive and unique")
            for activity in activities:
                if (
                    activity.program_version_id != version.id
                    or activity.program_id != version.program_id
                    or activity.scope != version.scope
                    or activity.tenant_id != version.tenant_id
                    or activity.module_id != module.id
                ):
                    raise CatalogConflictError("activity scope does not match its hierarchy")
        for edge in self._all_prerequisites():
            if edge.program_version_id != version.id:
                continue
            if edge.module_id not in module_ids or edge.prerequisite_module_id not in module_ids:
                raise PrerequisiteConflictError("prerequisite edge references another version")
            positions = {module.id: module.position for module in modules}
            if positions[edge.prerequisite_module_id] >= positions[edge.module_id]:
                raise PrerequisiteConflictError("prerequisites must point to earlier modules")

    def _validate_publication_provenance(self, version: ProgramVersionSnapshot) -> None:
        if (
            version.content_digest is None
            or _CONTENT_DIGEST.fullmatch(version.content_digest) is None
        ):
            raise CatalogPublicationProvenanceError(
                "publication requires a lowercase SHA-256 content_digest"
            )
        for field_name, value in (
            ("content_source_ref", version.content_source_ref),
            ("content_reviewed_by", version.content_reviewed_by),
        ):
            if value is None or not value.strip():
                raise CatalogPublicationProvenanceError(
                    f"publication requires non-blank {field_name}"
                )
        if version.content_reviewed_at is None:
            raise CatalogPublicationProvenanceError("publication requires content_reviewed_at")
        if (
            version.content_reviewed_at.tzinfo is None
            or version.content_reviewed_at.utcoffset() is None
        ):
            raise CatalogPublicationProvenanceError(
                "publication requires a timezone-aware content_reviewed_at"
            )
        _as_utc(version.content_reviewed_at)
        if version.release_id is None or _RELEASE_ID.fullmatch(version.release_id) is None:
            raise CatalogPublicationProvenanceError(
                "publication requires a full lowercase Git release_id"
            )
        if version.content_seed_kind == _TECHNICAL_VALIDATION_CONTENT_KIND:
            if not self._allow_technical_validation_publication:
                raise CatalogPublicationProvenanceError(
                    "technical-validation content publication is disabled in this environment"
                )
        elif version.content_seed_kind != _REVIEWED_CONTENT_KIND:
            raise CatalogPublicationProvenanceError(
                "publication requires reviewed or technical-validation content provenance"
            )

    def _canonical_content_digest(self, version: ProgramVersionSnapshot) -> str:
        program = self._store.get_program(version.program_id)
        if program is None:
            raise CatalogConflictError("program version references a missing program")
        modules = tuple(
            sorted(
                self._store.list_modules(version.id),
                key=lambda module: (module.position, module.id.hex),
            )
        )
        positions = {module.id: module.position for module in modules}
        prerequisites_by_module: dict[UUID, list[int]] = {}
        for edge in self._all_prerequisites():
            if edge.program_version_id != version.id:
                continue
            prerequisite_position = positions.get(edge.prerequisite_module_id)
            if edge.module_id not in positions or prerequisite_position is None:
                raise PrerequisiteConflictError("prerequisite edge references another version")
            prerequisites_by_module.setdefault(edge.module_id, []).append(prerequisite_position)
        canonical_modules = tuple(
            CanonicalModuleContent(
                position=module.position,
                title=module.title,
                prerequisite_positions=tuple(sorted(prerequisites_by_module.get(module.id, ()))),
                activities=tuple(
                    CanonicalActivityContent(
                        position=activity.position,
                        kind=activity.kind,
                        title=activity.title,
                        is_required=activity.is_required,
                        prompt=activity.prompt,
                    )
                    for activity in sorted(
                        self._store.list_activities(module.id),
                        key=lambda item: (item.position, item.id.hex),
                    )
                ),
            )
            for module in modules
        )
        return canonical_catalog_content_digest(
            program_slug=program.slug,
            program_title=program.title,
            modules=canonical_modules,
        )

    def _all_prerequisites(self) -> tuple[ModulePrerequisiteSnapshot, ...]:
        if isinstance(self._store, InMemoryCatalogStore):
            return tuple(self._store.prerequisites.values())
        list_all = getattr(self._store, "list_all_prerequisites", None)
        if callable(list_all):
            return tuple(list_all())
        return ()

    def _would_cycle(self, module_id: UUID, prerequisite_id: UUID, version_id: UUID) -> bool:
        edges: dict[UUID, set[UUID]] = {}
        for edge in self._all_prerequisites():
            if edge.program_version_id == version_id:
                edges.setdefault(edge.module_id, set()).add(edge.prerequisite_module_id)
        edges.setdefault(module_id, set()).add(prerequisite_id)
        pending = [prerequisite_id]
        seen: set[UUID] = set()
        while pending:
            current = pending.pop()
            if current == module_id:
                return True
            if current in seen:
                continue
            seen.add(current)
            pending.extend(edges.get(current, ()))
        return False


class AsyncCatalogApplication:
    """Authorized catalog commands using one explicit caller-owned transaction."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Callable[[], datetime] | None = None,
        allow_technical_validation_publication: bool = False,
    ) -> None:
        self._session = session
        self._clock = clock
        self._allow_technical_validation_publication = allow_technical_validation_publication

    def _require_transaction(self) -> None:
        transaction = self._session.get_transaction()
        sync_transaction = None if transaction is None else transaction.sync_transaction
        if (
            sync_transaction is None
            or sync_transaction.origin is not SessionTransactionOrigin.BEGIN
        ):
            raise CatalogTransactionRequiredError(
                "catalog commands require an explicit caller-owned AsyncSession transaction"
            )

    async def _authorize_admin(
        self,
        actor: ActorContext,
        *,
        tenant_id: UUID | None,
        permission: str,
    ) -> None:
        self._require_transaction()
        if permission not in actor.permissions:
            raise CatalogAccessDeniedError(f"catalog command requires {permission}")
        person = await self._session.scalar(
            select(Person).where(Person.id == actor.person_id).with_for_update()
        )
        if person is None or person.status != PersonStatus.ACTIVE.value:
            raise CatalogAccessDeniedError("catalog actor is unavailable")
        if tenant_id is None:
            if actor.tenant_id is not None:
                raise CatalogAccessDeniedError("global catalog authoring requires global context")
            return
        if actor.tenant_id != tenant_id:
            raise CatalogAccessDeniedError("catalog actor selected another tenant")
        tenant = await self._session.scalar(
            select(Tenant).where(Tenant.id == tenant_id).with_for_update()
        )
        membership = await self._session.scalar(
            select(Membership)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.person_id == actor.person_id,
            )
            .with_for_update()
        )
        if (
            tenant is None
            or tenant.status != TenantStatus.ACTIVE.value
            or membership is None
            or membership.status != MembershipStatus.ACTIVE.value
            or membership.ended_at is not None
            or membership.role not in {"admin", "owner"}
        ):
            raise CatalogAccessDeniedError("catalog command requires active admin membership")

    async def _execute(self, operation: Callable[[CatalogService], _T]) -> _T:
        async with self._session.begin_nested():
            transaction = SqlAlchemyCatalogUnitOfWork(self._session)
            async with transaction:

                def invoke(sync_session: Session) -> _T:
                    return operation(
                        CatalogService(
                            SqlAlchemyCatalogStore(sync_session),
                            clock=self._clock,
                            allow_technical_validation_publication=(
                                self._allow_technical_validation_publication
                            ),
                        )
                    )

                result = await transaction.run_sync(invoke)
                await transaction.commit()
                return result

    async def create_program(
        self,
        *,
        actor: ActorContext,
        tenant_id: UUID | None,
        slug: str,
        title: str,
        scope: CatalogScope | str | None = None,
        program_id: UUID | None = None,
        now: datetime | None = None,
    ) -> ProgramSnapshot:
        await self._authorize_admin(actor, tenant_id=tenant_id, permission=CATALOG_WRITE_PERMISSION)
        return await self._execute(
            lambda catalog: catalog.create_program(
                tenant_id=tenant_id,
                slug=slug,
                title=title,
                scope=scope,
                program_id=program_id,
                now=now,
            )
        )

    async def create_version(
        self,
        program_id: UUID,
        *,
        actor: ActorContext,
        tenant_id: UUID | None,
        version_number: int | None = None,
        supersedes_version_id: UUID | None = None,
        version_id: UUID | None = None,
        content_digest: str | None = None,
        content_source_ref: str | None = None,
        content_reviewed_by: str | None = None,
        content_reviewed_at: datetime | None = None,
        release_id: str | None = None,
        content_seed_kind: str | None = None,
        now: datetime | None = None,
    ) -> ProgramVersionSnapshot:
        await self._authorize_admin(actor, tenant_id=tenant_id, permission=CATALOG_WRITE_PERMISSION)
        return await self._execute(
            lambda catalog: catalog.create_version(
                program_id,
                tenant_id=tenant_id,
                version_number=version_number,
                supersedes_version_id=supersedes_version_id,
                version_id=version_id,
                content_digest=content_digest,
                content_source_ref=content_source_ref,
                content_reviewed_by=content_reviewed_by,
                content_reviewed_at=content_reviewed_at,
                release_id=release_id,
                content_seed_kind=content_seed_kind,
                now=now,
            )
        )

    async def add_module(
        self,
        program_version_id: UUID,
        *,
        actor: ActorContext,
        tenant_id: UUID | None,
        title: str,
        position: int | None = None,
        module_id: UUID | None = None,
    ) -> ModuleSnapshot:
        await self._authorize_admin(actor, tenant_id=tenant_id, permission=CATALOG_WRITE_PERMISSION)
        return await self._execute(
            lambda catalog: catalog.add_module(
                program_version_id,
                tenant_id=tenant_id,
                title=title,
                position=position,
                module_id=module_id,
            )
        )

    async def add_activity(
        self,
        module_id: UUID,
        *,
        actor: ActorContext,
        tenant_id: UUID | None,
        kind: ActivityKind | str,
        title: str,
        prompt: str | None = None,
        position: int | None = None,
        activity_id: UUID | None = None,
        is_required: bool = True,
    ) -> ActivitySnapshot:
        await self._authorize_admin(actor, tenant_id=tenant_id, permission=CATALOG_WRITE_PERMISSION)
        return await self._execute(
            lambda catalog: catalog.add_activity(
                module_id,
                tenant_id=tenant_id,
                kind=kind,
                title=title,
                prompt=prompt,
                position=position,
                activity_id=activity_id,
                is_required=is_required,
            )
        )

    async def add_module_prerequisite(
        self,
        module_id: UUID,
        prerequisite_module_id: UUID,
        *,
        actor: ActorContext,
        tenant_id: UUID | None,
        prerequisite_id: UUID | None = None,
    ) -> ModulePrerequisiteSnapshot:
        await self._authorize_admin(actor, tenant_id=tenant_id, permission=CATALOG_WRITE_PERMISSION)
        return await self._execute(
            lambda catalog: catalog.add_module_prerequisite(
                module_id,
                prerequisite_module_id,
                tenant_id=tenant_id,
                prerequisite_id=prerequisite_id,
            )
        )

    async def publish_version(
        self,
        program_version_id: UUID,
        *,
        actor: ActorContext,
        tenant_id: UUID | None,
        now: datetime | None = None,
    ) -> ProgramVersionSnapshot:
        await self._authorize_admin(
            actor,
            tenant_id=tenant_id,
            permission=CATALOG_PUBLISH_PERMISSION,
        )
        return await self._execute(
            lambda catalog: catalog.publish_version(
                program_version_id,
                tenant_id=tenant_id,
                now=now,
            )
        )

    async def pin_version(
        self,
        *,
        actor: ActorContext,
        tenant_id: UUID,
        program_id: UUID,
        program_version_id: UUID,
        pinned_at: datetime | None = None,
    ) -> LearnerVersionPinSnapshot:
        self._require_transaction()
        if actor.tenant_id != tenant_id:
            raise LearnerMembershipRequiredError("learner pin requires the selected tenant")
        person = await self._session.scalar(
            select(Person).where(Person.id == actor.person_id).with_for_update()
        )
        tenant = await self._session.scalar(
            select(Tenant).where(Tenant.id == tenant_id).with_for_update()
        )
        membership = await self._session.scalar(
            select(Membership)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.person_id == actor.person_id,
            )
            .with_for_update()
        )
        if (
            person is None
            or person.status != PersonStatus.ACTIVE.value
            or tenant is None
            or tenant.status != TenantStatus.ACTIVE.value
            or membership is None
            or membership.status != MembershipStatus.ACTIVE.value
            or membership.ended_at is not None
            or membership.role != "learner"
        ):
            raise LearnerMembershipRequiredError("learner has no active membership in this tenant")

        def pin(catalog: CatalogService) -> LearnerVersionPinSnapshot:
            store = cast(SqlAlchemyCatalogStore, catalog._store)  # noqa: SLF001
            service = LearnerVersionPinningService(
                store,
                active_membership=lambda person_id, selected_tenant_id: (
                    person_id == actor.person_id and selected_tenant_id == tenant_id
                ),
                clock=self._clock,
            )
            return service.pin_version(
                learner_person_id=actor.person_id,
                tenant_id=tenant_id,
                program_id=program_id,
                program_version_id=program_version_id,
                pinned_at=pinned_at,
            )

        return await self._execute(pin)


class LearnerPinningPort(Protocol):
    """Narrow seam for a future enrollment/entitlement module."""

    def pin_version(
        self,
        *,
        learner_person_id: UUID,
        tenant_id: UUID,
        program_id: UUID,
        program_version_id: UUID,
        pinned_at: datetime | None = None,
    ) -> LearnerVersionPinSnapshot: ...


class LearnerVersionPinningService:
    """Pin an exact published version without granting enrollment or access."""

    def __init__(
        self,
        store: CatalogStore,
        *,
        active_membership: Callable[[UUID, UUID], bool] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._catalog = CatalogService(store, clock=clock)
        self._active_membership = active_membership
        self._clock = clock or (lambda: datetime.now(UTC))

    def pin_version(
        self,
        *,
        learner_person_id: UUID,
        tenant_id: UUID,
        program_id: UUID,
        program_version_id: UUID,
        pinned_at: datetime | None = None,
    ) -> LearnerVersionPinSnapshot:
        if self._active_membership is None:
            raise LearnerMembershipRequiredError(
                "catalog membership authorization is required and fails closed"
            )
        if not self._active_membership(learner_person_id, tenant_id):
            raise LearnerMembershipRequiredError("learner has no active membership in this tenant")
        if tenant_id is None:
            raise LearnerMembershipRequiredError("a learner pin requires an explicit tenant")
        program = self._catalog.get_program(program_id, tenant_id=tenant_id)
        version = self._catalog.get_version(
            program_version_id,
            tenant_id=tenant_id,
            published_only=True,
        )
        if version.program_id != program.id:
            raise CatalogAccessDeniedError("version does not belong to the selected program")
        existing = self._store.get_pin(tenant_id, learner_person_id, program.id)
        pin_time = _now(pinned_at or self._clock())
        pin = LearnerVersionPinSnapshot(
            id=existing.id if existing is not None else uuid4(),
            tenant_id=tenant_id,
            learner_person_id=learner_person_id,
            program_id=program.id,
            program_scope=program.scope,
            program_tenant_id=program.tenant_id,
            program_version_id=version.id,
            pinned_at=pin_time,
            program_owner_key=program.owner_key,
        )
        if existing is None:
            self._store.save_pin(pin)
        else:
            self._store.replace_pin(pin)
        return pin

    def pin(self, **kwargs: object) -> LearnerVersionPinSnapshot:
        """Short alias for :meth:`pin_version`."""

        return self.pin_version(**kwargs)  # type: ignore[arg-type]

    def get_pin(
        self,
        *,
        learner_person_id: UUID,
        tenant_id: UUID,
        program_id: UUID,
    ) -> LearnerVersionPinSnapshot:
        if self._active_membership is None:
            raise LearnerMembershipRequiredError(
                "catalog membership authorization is required and fails closed"
            )
        if not self._active_membership(learner_person_id, tenant_id):
            raise LearnerMembershipRequiredError("learner has no active membership in this tenant")
        self._catalog.get_program(program_id, tenant_id=tenant_id)
        pin = self._store.get_pin(tenant_id, learner_person_id, program_id)
        if pin is None:
            raise CatalogNotFoundError("learner has no pin for this program")
        return pin


LearnerPinningService = LearnerVersionPinningService
PublicationService = CatalogService
CatalogApplicationService = AsyncCatalogApplication


__all__ = [
    "ActivitySnapshot",
    "AsyncCatalogApplication",
    "CATALOG_PUBLISH_PERMISSION",
    "CATALOG_WRITE_PERMISSION",
    "CatalogAccessDeniedError",
    "CatalogApplicationService",
    "CatalogConflictError",
    "CatalogContentDigestMismatchError",
    "CatalogNotFoundError",
    "CatalogPublicationProvenanceError",
    "CatalogService",
    "CatalogServiceError",
    "CatalogStore",
    "CatalogTenantAccessDeniedError",
    "CatalogTransactionRequiredError",
    "CatalogValidationError",
    "DraftRequiredError",
    "InMemoryCatalogStore",
    "InvalidActivityKindError",
    "LearnerMembershipRequiredError",
    "LearnerPinningService",
    "LearnerPinningError",
    "LearnerVersionPinSnapshot",
    "LearnerVersionPinningService",
    "LearnerPinningPort",
    "ModulePrerequisiteSnapshot",
    "ModuleSnapshot",
    "OrderingConflictError",
    "PrerequisiteConflictError",
    "ProgramSnapshot",
    "ProgramVersionSnapshot",
    "PublicationService",
    "PublishedVersionImmutableError",
    "SqlAlchemyCatalogStore",
    "SqlAlchemyCatalogUnitOfWork",
    "SupersessionRequiredError",
]
