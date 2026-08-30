"""SQLAlchemy models for the versioned Authority Closers catalog.

The catalog is deliberately a content foundation, not an enrollment system.
Programs may be tenant-owned or global.  Every descendant carries the scope
needed to make the parent relationship checkable by the database as well as by
the application service.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    event,
    func,
    text,
)
from sqlalchemy import (
    inspect as sa_inspect,
)
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from ac_platform.db.base import Base


class CatalogScope(StrEnum):
    """Ownership scope for a catalog aggregate."""

    GLOBAL = "global"
    TENANT = "tenant"


# A non-null owner key makes global rows safe participants in composite foreign
# keys.  Nullable tenant columns are retained as descriptive/API fields, but
# they are never part of a catalog hierarchy FK.
GLOBAL_CATALOG_OWNER_KEY = UUID("00000000-0000-0000-0000-000000000000")


class ProgramVersionStatus(StrEnum):
    """Lifecycle states for a versioned program snapshot."""

    DRAFT = "draft"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"


class ActivityKind(StrEnum):
    """The only activity kinds exposed by the G1 Free Course foundation."""

    VIDEO = "VIDEO"
    REFLECTION = "REFLECTION"
    IMPLEMENTATION_CHALLENGE = "IMPLEMENTATION_CHALLENGE"
    REVIEW = "REVIEW"
    IMPROVE = "IMPROVE"


# Compatibility aliases keep the domain vocabulary discoverable without
# creating a second, potentially divergent enum.
ProgramScope = CatalogScope
VersionStatus = ProgramVersionStatus

SUPPORTED_ACTIVITY_KINDS: frozenset[str] = frozenset(kind.value for kind in ActivityKind)
ACTIVITY_PROMPT_MAX_LENGTH = 2000
IMMUTABLE_VERSION_STATUSES: frozenset[str] = frozenset(
    {ProgramVersionStatus.PUBLISHED.value, ProgramVersionStatus.SUPERSEDED.value}
)


def utc_now() -> datetime:
    """Return an aware UTC timestamp suitable for application-side defaults."""

    return datetime.now(UTC)


def _scope_constraints(table_name: str) -> tuple[CheckConstraint, CheckConstraint]:
    return (
        CheckConstraint(
            f"scope IN ('{CatalogScope.GLOBAL.value}', '{CatalogScope.TENANT.value}')",
            name=f"scope_supported_{table_name}",
        ),
        CheckConstraint(
            "(scope = 'global' AND tenant_id IS NULL) "
            "OR (scope = 'tenant' AND tenant_id IS NOT NULL)",
            name=f"scope_tenant_match_{table_name}",
        ),
    )


def _owner_key_constraint(table_name: str) -> CheckConstraint:
    return CheckConstraint(
        f"(scope = 'global' AND owner_key = '{GLOBAL_CATALOG_OWNER_KEY.hex}') "
        "OR (scope = 'tenant' AND owner_key = tenant_id)",
        name=f"scope_owner_match_{table_name}",
    )


def _populate_owner_key(_mapper: Any, _connection: Any, target: Any) -> None:
    """Fill the normalized owner key for ordinary ORM inserts.

    Core SQL and explicit mismatches still go through the non-null column,
    scope check, and parent composite FK, so this convenience cannot weaken
    the database boundary.
    """

    if getattr(target, "owner_key", None) is not None:
        return
    scope = str(getattr(target, "scope", ""))
    tenant_id = getattr(target, "tenant_id", None)
    if scope == CatalogScope.GLOBAL.value:
        target.owner_key = GLOBAL_CATALOG_OWNER_KEY
    elif scope == CatalogScope.TENANT.value and tenant_id is not None:
        target.owner_key = tenant_id


class Program(Base):
    """Stable catalog identity whose learner-facing content is versioned."""

    __tablename__ = "programs"
    __table_args__ = (
        UniqueConstraint("id", "scope", "owner_key", name="uq_programs_scope_identity"),
        CheckConstraint("length(trim(slug)) > 0", name="slug_nonblank"),
        CheckConstraint("length(trim(title)) > 0", name="title_nonblank"),
        *_scope_constraints("programs"),
        _owner_key_constraint("programs"),
        Index(
            "uq_programs_global_slug",
            "slug",
            unique=True,
            postgresql_where=text("scope = 'global'"),
            sqlite_where=text("scope = 'global'"),
        ),
        Index(
            "uq_programs_tenant_slug",
            "tenant_id",
            "slug",
            unique=True,
            postgresql_where=text("scope = 'tenant'"),
            sqlite_where=text("scope = 'tenant'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    scope: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=CatalogScope.TENANT.value,
        server_default=CatalogScope.TENANT.value,
    )
    owner_key: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    tenant_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", name="fk_programs_tenant_id_tenants"),
        nullable=True,
    )
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )

    versions: Mapped[list[ProgramVersion]] = relationship(
        back_populates="program",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ProgramVersion.version_number",
    )

    @property
    def is_global(self) -> bool:
        return self.scope == CatalogScope.GLOBAL.value


class ProgramVersion(Base):
    """One immutable-after-publication snapshot of a :class:`Program`."""

    __tablename__ = "program_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["program_id", "scope", "owner_key"],
            ["programs.id", "programs.scope", "programs.owner_key"],
            name="fk_program_versions_program_scope",
        ),
        ForeignKeyConstraint(
            ["supersedes_version_id", "program_id", "scope", "owner_key"],
            [
                "program_versions.id",
                "program_versions.program_id",
                "program_versions.scope",
                "program_versions.owner_key",
            ],
            name="fk_program_versions_supersedes_same_program",
        ),
        UniqueConstraint(
            "id",
            "program_id",
            "scope",
            "owner_key",
            name="uq_program_versions_scope_identity",
        ),
        UniqueConstraint(
            "program_id",
            "version_number",
            name="uq_program_versions_program_number",
        ),
        UniqueConstraint(
            "program_id",
            "content_digest",
            name="uq_program_versions_content_digest",
        ),
        CheckConstraint("version_number > 0", name="version_number_positive"),
        CheckConstraint(
            "status IN ('draft', 'published', 'superseded')",
            name="status_supported",
        ),
        CheckConstraint(
            "published_at IS NULL OR status IN ('published', 'superseded')",
            name="published_timestamp_requires_publication",
        ),
        CheckConstraint(
            "supersedes_version_id IS NULL OR supersedes_version_id <> id",
            name="cannot_supersede_self",
        ),
        CheckConstraint(
            "content_digest IS NULL OR length(content_digest) = 64",
            name="content_digest_sha256",
        ),
        CheckConstraint(
            "content_source_ref IS NULL OR length(trim(content_source_ref)) > 0",
            name="content_source_ref_nonblank",
        ),
        CheckConstraint(
            "content_reviewed_by IS NULL OR length(trim(content_reviewed_by)) > 0",
            name="content_reviewed_by_nonblank",
        ),
        CheckConstraint(
            "release_id IS NULL OR length(trim(release_id)) > 0",
            name="release_id_nonblank",
        ),
        CheckConstraint(
            "content_seed_kind IS NULL OR length(trim(content_seed_kind)) > 0",
            name="content_seed_kind_nonblank",
        ),
        *_scope_constraints("program_versions"),
        _owner_key_constraint("program_versions"),
        Index("ix_program_versions_program_status", "program_id", "status"),
        Index(
            "uq_program_versions_one_current_published",
            "program_id",
            unique=True,
            postgresql_where=text("status = 'published'"),
            sqlite_where=text("status = 'published'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    program_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    scope: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=CatalogScope.TENANT.value,
        server_default=CatalogScope.TENANT.value,
    )
    owner_key: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    tenant_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", name="fk_program_versions_tenant_id_tenants"),
        nullable=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ProgramVersionStatus.DRAFT.value,
        server_default=ProgramVersionStatus.DRAFT.value,
    )
    supersedes_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_source_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content_reviewed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    content_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    release_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content_seed_kind: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )

    program: Mapped[Program] = relationship(back_populates="versions")
    modules: Mapped[list[Module]] = relationship(
        back_populates="program_version",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Module.position",
    )

    @property
    def is_immutable(self) -> bool:
        return self.status in IMMUTABLE_VERSION_STATUSES

    @property
    def is_published(self) -> bool:
        return self.status in IMMUTABLE_VERSION_STATUSES


class Module(Base):
    """Ordered module within one program version."""

    __tablename__ = "modules"
    __table_args__ = (
        ForeignKeyConstraint(
            ["program_version_id", "program_id", "scope", "owner_key"],
            [
                "program_versions.id",
                "program_versions.program_id",
                "program_versions.scope",
                "program_versions.owner_key",
            ],
            name="fk_modules_program_version_scope",
        ),
        UniqueConstraint(
            "id",
            "program_version_id",
            "program_id",
            "scope",
            "owner_key",
            name="uq_modules_scope_identity",
        ),
        UniqueConstraint(
            "program_version_id",
            "position",
            name="uq_modules_version_position",
        ),
        CheckConstraint("position > 0", name="position_positive"),
        CheckConstraint("length(trim(title)) > 0", name="title_nonblank"),
        *_scope_constraints("modules"),
        _owner_key_constraint("modules"),
        Index("ix_modules_version_position", "program_version_id", "position"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    program_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    scope: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=CatalogScope.TENANT.value,
        server_default=CatalogScope.TENANT.value,
    )
    owner_key: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    tenant_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", name="fk_modules_tenant_id_tenants"),
        nullable=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )

    program_version: Mapped[ProgramVersion] = relationship(back_populates="modules")
    activities: Mapped[list[Activity]] = relationship(
        back_populates="module",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Activity.position",
    )

    @property
    def order_index(self) -> int:
        """Stable vocabulary alias for callers that call ordering an index."""

        return self.position


class ModulePrerequisite(Base):
    """A same-version, directed prerequisite edge between two modules."""

    __tablename__ = "module_prerequisites"
    __table_args__ = (
        ForeignKeyConstraint(
            ["program_version_id", "program_id", "scope", "owner_key"],
            [
                "program_versions.id",
                "program_versions.program_id",
                "program_versions.scope",
                "program_versions.owner_key",
            ],
            name="fk_module_prerequisites_program_version_scope",
        ),
        ForeignKeyConstraint(
            ["module_id", "program_version_id", "program_id", "scope", "owner_key"],
            [
                "modules.id",
                "modules.program_version_id",
                "modules.program_id",
                "modules.scope",
                "modules.owner_key",
            ],
            name="fk_module_prerequisites_module_scope",
        ),
        ForeignKeyConstraint(
            [
                "prerequisite_module_id",
                "program_version_id",
                "program_id",
                "scope",
                "owner_key",
            ],
            [
                "modules.id",
                "modules.program_version_id",
                "modules.program_id",
                "modules.scope",
                "modules.owner_key",
            ],
            name="fk_module_prerequisites_required_module_scope",
        ),
        UniqueConstraint(
            "id",
            "program_version_id",
            "program_id",
            "scope",
            "owner_key",
            name="uq_module_prerequisites_scope_identity",
        ),
        UniqueConstraint(
            "module_id",
            "prerequisite_module_id",
            name="uq_module_prerequisites_edge",
        ),
        CheckConstraint(
            "module_id <> prerequisite_module_id",
            name="module_prerequisite_not_self",
        ),
        *_scope_constraints("module_prerequisites"),
        _owner_key_constraint("module_prerequisites"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    program_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    scope: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=CatalogScope.TENANT.value,
        server_default=CatalogScope.TENANT.value,
    )
    owner_key: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    tenant_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", name="fk_module_prerequisites_tenant_id_tenants"),
        nullable=True,
    )
    module_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    prerequisite_module_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


class Activity(Base):
    """Ordered, typed learner activity in one module."""

    __tablename__ = "activities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["module_id", "program_version_id", "program_id", "scope", "owner_key"],
            [
                "modules.id",
                "modules.program_version_id",
                "modules.program_id",
                "modules.scope",
                "modules.owner_key",
            ],
            name="fk_activities_module_scope",
        ),
        UniqueConstraint(
            "id",
            "module_id",
            "program_version_id",
            "program_id",
            "scope",
            "owner_key",
            name="uq_activities_scope_identity",
        ),
        UniqueConstraint("module_id", "position", name="uq_activities_module_position"),
        CheckConstraint("position > 0", name="position_positive"),
        CheckConstraint(
            "kind IN ('VIDEO', 'REFLECTION', 'IMPLEMENTATION_CHALLENGE', 'REVIEW', 'IMPROVE')",
            name="kind_supported",
        ),
        CheckConstraint("length(trim(title)) > 0", name="title_nonblank"),
        CheckConstraint(
            "prompt IS NULL OR (length(trim(prompt)) > 0 AND length(prompt) <= 2000)",
            name="prompt_valid",
        ),
        *_scope_constraints("activities"),
        _owner_key_constraint("activities"),
        Index("ix_activities_module_position", "module_id", "position"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    module_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    scope: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=CatalogScope.TENANT.value,
        server_default=CatalogScope.TENANT.value,
    )
    owner_key: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    tenant_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", name="fk_activities_tenant_id_tenants"),
        nullable=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    prompt: Mapped[str | None] = mapped_column(String(ACTIVITY_PROMPT_MAX_LENGTH), nullable=True)
    is_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )

    module: Mapped[Module] = relationship(back_populates="activities")

    @property
    def order_index(self) -> int:
        return self.position


class LearnerVersionPin(Base):
    """The future enrollment seam: one learner's selected catalog version.

    This row is intentionally not an enrollment or entitlement.  It records
    only the version selected for a learner in a tenant context so a later
    enrollment module can consume the decision without changing catalog
    history.
    """

    __tablename__ = "learner_version_pins"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "learner_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_learner_version_pins_membership",
        ),
        ForeignKeyConstraint(
            ["program_id", "program_scope", "program_owner_key"],
            ["programs.id", "programs.scope", "programs.owner_key"],
            name="fk_learner_version_pins_program_scope",
        ),
        ForeignKeyConstraint(
            [
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "program_versions.id",
                "program_versions.program_id",
                "program_versions.scope",
                "program_versions.owner_key",
            ],
            name="fk_learner_version_pins_version_scope",
        ),
        UniqueConstraint(
            "tenant_id",
            "learner_person_id",
            "program_id",
            name="uq_learner_version_pins_learner_program",
        ),
        CheckConstraint(
            "program_scope IN ('global', 'tenant')",
            name="program_scope_supported",
        ),
        CheckConstraint(
            "(program_scope = 'global' AND program_tenant_id IS NULL) "
            "OR (program_scope = 'tenant' AND program_tenant_id IS NOT NULL)",
            name="program_scope_tenant_match",
        ),
        CheckConstraint(
            f"(program_scope = 'global' AND program_owner_key = '{GLOBAL_CATALOG_OWNER_KEY.hex}') "
            "OR (program_scope = 'tenant' AND program_owner_key = program_tenant_id)",
            name="program_scope_owner_match",
        ),
        CheckConstraint(
            "program_scope = 'global' OR program_tenant_id = tenant_id",
            name="tenant_pin_matches_program_owner",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    learner_person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    program_tenant_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", name="fk_learner_version_pins_program_tenant_id_tenants"),
        nullable=True,
    )
    program_owner_key: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    pinned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )


def _populate_pin_owner_key(_mapper: Any, _connection: Any, target: LearnerVersionPin) -> None:
    """Fill the normalized pin owner key for ordinary ORM inserts."""

    if target.program_owner_key is not None:
        return
    if target.program_scope == CatalogScope.GLOBAL.value:
        target.program_owner_key = GLOBAL_CATALOG_OWNER_KEY
    elif target.program_scope == CatalogScope.TENANT.value and target.program_tenant_id is not None:
        target.program_owner_key = target.program_tenant_id


_VERSION_PROTECTED_ATTRIBUTES = (
    "program_id",
    "scope",
    "owner_key",
    "tenant_id",
    "version_number",
    "supersedes_version_id",
    "published_at",
    "content_digest",
    "content_source_ref",
    "content_reviewed_by",
    "content_reviewed_at",
    "release_id",
    "content_seed_kind",
)


def _old_value(instance: object, attribute: str) -> object:
    state = cast(Any, sa_inspect(instance))
    history = state.attrs[attribute].history
    if history.deleted:
        return history.deleted[0]
    return getattr(instance, attribute)


def _has_changes(instance: object, attributes: tuple[str, ...]) -> bool:
    state = cast(Any, sa_inspect(instance))
    return any(state.attrs[attribute].history.has_changes() for attribute in attributes)


def _version_can_change_during_flush(version: ProgramVersion) -> bool:
    old_status = _old_value(version, "status")
    new_status = version.status
    if old_status == ProgramVersionStatus.DRAFT.value:
        return new_status in {
            ProgramVersionStatus.DRAFT.value,
            ProgramVersionStatus.PUBLISHED.value,
        }
    if (
        old_status == ProgramVersionStatus.PUBLISHED.value
        and new_status == ProgramVersionStatus.SUPERSEDED.value
    ):
        return not _has_changes(version, _VERSION_PROTECTED_ATTRIBUTES)
    if old_status in IMMUTABLE_VERSION_STATUSES:
        return not _has_changes(
            version,
            _VERSION_PROTECTED_ATTRIBUTES + ("status", "superseded_at"),
        )
    return False


def _version_allows_child_flush(version: ProgramVersion) -> bool:
    """Return whether child rows may flush as part of draft publication."""

    old_status = _old_value(version, "status")
    return old_status == ProgramVersionStatus.DRAFT.value


def _version_for_child(session: Session, child: object) -> ProgramVersion | None:
    version_ids: set[UUID] = set()
    current_id = getattr(child, "program_version_id", None)
    if isinstance(current_id, UUID):
        version_ids.add(current_id)
    state = cast(Any, sa_inspect(child))
    history = state.attrs.program_version_id.history
    version_ids.update(value for value in history.deleted if isinstance(value, UUID))
    for version_id in version_ids:
        version = session.get(ProgramVersion, version_id)
        if version is not None:
            return version
    return None


def _enforce_catalog_immutability(
    session: Session,
    _flush_context: object,
    _instances: object,
) -> None:
    """Reject ORM edits/deletes that would rewrite an immutable version.

    Database constraints protect scope and identity.  This session boundary
    protects the richer state transition because a normal SQL CHECK cannot
    inspect the previous row value.  Direct SQL remains outside the domain
    write path and is not used by catalog services.
    """

    for instance in session.dirty:
        if isinstance(instance, ProgramVersion) and not _version_can_change_during_flush(instance):
            raise ValueError("published program versions are immutable; create a new version")
        if isinstance(instance, (Module, Activity, ModulePrerequisite)):
            version = _version_for_child(session, instance)
            if version is not None and not _version_allows_child_flush(version):
                raise ValueError("published catalog content is immutable; create a new version")

    for instance in session.deleted:
        if isinstance(instance, ProgramVersion):
            status = str(instance.status)
            if status in IMMUTABLE_VERSION_STATUSES:
                raise ValueError("published program versions cannot be deleted")
        elif isinstance(instance, (Module, Activity, ModulePrerequisite)):
            version = _version_for_child(session, instance)
            if version is not None and not _version_allows_child_flush(version):
                raise ValueError("published catalog content cannot be deleted")


for _owner_model in (Program, ProgramVersion, Module, ModulePrerequisite, Activity):
    event.listen(_owner_model, "before_insert", _populate_owner_key)
event.listen(LearnerVersionPin, "before_insert", _populate_pin_owner_key)


event.listen(Session, "before_flush", _enforce_catalog_immutability)


__all__ = [
    "Activity",
    "ActivityKind",
    "CatalogScope",
    "GLOBAL_CATALOG_OWNER_KEY",
    "IMMUTABLE_VERSION_STATUSES",
    "LearnerVersionPin",
    "Module",
    "ModulePrerequisite",
    "Program",
    "ProgramScope",
    "ProgramVersion",
    "ProgramVersionStatus",
    "SUPPORTED_ACTIVITY_KINDS",
    "VersionStatus",
    "utc_now",
]
