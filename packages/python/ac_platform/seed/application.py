"""Application path for the reviewed, versioned staging catalog seed."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TypeVar
from uuid import UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.application.release_identity import (
    ReleaseIdentityError,
    read_baked_release_id,
)
from ac_platform.catalog.models import CatalogScope, Program, ProgramVersion, ProgramVersionStatus
from ac_platform.catalog.services import (
    AsyncCatalogApplication,
    CatalogAccessDeniedError,
    ProgramVersionSnapshot,
)
from ac_platform.identity.models import Person, PersonStatus
from ac_platform.kernel.authz import ActorContext
from ac_platform.seed.contract import FreeCourseSeed, TechnicalValidationSeed
from ac_platform.tenancy.models import Membership, MembershipStatus, Tenant, TenantStatus

_SEED_NAMESPACE = UUID("d38c3bde-87e7-4bd1-92d2-0f1433d17cc2")
_RELEASE_ID = re.compile(r"^[0-9a-f]{40}$")
_SEED_LOCK_NAMESPACE = "authority-closers:staging-seed:v1"
_SEED_PERMISSIONS = frozenset({"catalog_write", "catalog_publish"})
_ProvenanceT = TypeVar("_ProvenanceT")


class SeedApplicationError(RuntimeError):
    """The seed cannot be applied without weakening catalog invariants."""


class SeedAlreadyApplied(SeedApplicationError):
    """The content was previously published and must not be republished."""


def _stable_id(kind: str, value: str) -> UUID:
    return uuid5(_SEED_NAMESPACE, f"{kind}:{value}")


@dataclass(frozen=True, slots=True)
class SeedApplicationResult:
    status: str
    program_id: UUID
    program_version_id: UUID
    version_number: int
    content_digest: str
    release_id: str
    content_source_ref: str
    content_reviewed_by: str
    content_reviewed_at: datetime
    seed_kind: str
    visible_program_count: int


class StagingSeedApplication:
    """Create/publish a reviewed snapshot through catalog application commands."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        environment: str,
        expected_release_id: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if environment not in {"staging", "test"}:
            raise SeedApplicationError("the staging seed is allowed only in staging or test")
        normalized_release_id = expected_release_id.strip()
        if not _RELEASE_ID.fullmatch(normalized_release_id):
            raise SeedApplicationError(
                "expected runtime release ID must be a full lowercase Git SHA"
            )
        if environment == "staging":
            try:
                baked_release_id = read_baked_release_id()
            except ReleaseIdentityError as error:
                raise SeedApplicationError(str(error)) from error
            if normalized_release_id != baked_release_id:
                raise SeedApplicationError(
                    "expected runtime release ID does not match the baked API release marker"
                )
        self._session = session
        self._environment = environment
        self._expected_release_id = normalized_release_id
        self._clock = clock or (lambda: datetime.now(UTC))

    async def apply(
        self,
        seed: FreeCourseSeed,
        *,
        actor: ActorContext,
    ) -> SeedApplicationResult:
        if seed.seed_kind != "reviewed":
            raise SeedApplicationError(
                "technical validation content requires the explicit technical-validation path"
            )
        try:
            return await self._apply(seed, actor=actor)
        except CatalogAccessDeniedError as exc:
            raise SeedApplicationError(
                "the seed actor must be an existing active person authorized for "
                "global catalog writing"
            ) from exc

    async def apply_technical_validation(
        self,
        seed: TechnicalValidationSeed,
        *,
        actor: ActorContext,
    ) -> SeedApplicationResult:
        if seed.seed_kind != "technical-validation":
            raise SeedApplicationError("the technical-validation path requires technical content")
        try:
            return await self._apply(seed, actor=actor)
        except CatalogAccessDeniedError as exc:
            raise SeedApplicationError(
                "the seed actor must be an existing active person authorized for "
                "global catalog writing"
            ) from exc

    async def _apply(
        self,
        seed: FreeCourseSeed,
        *,
        actor: ActorContext,
    ) -> SeedApplicationResult:
        if actor.tenant_id is not None:
            raise SeedApplicationError("the Free Course seed requires global catalog context")
        if seed.release_id != self._expected_release_id:
            raise SeedApplicationError(
                "seed release ID does not match the expected runtime release ID"
            )

        program_id = _stable_id("program", seed.seed_key)
        async with self._session.begin():
            await self._lock_seed_identity(seed)
            catalog_actor = await self._authorize_seed_actor(actor)
            program = await self._session.scalar(
                select(Program)
                .where(
                    Program.scope == CatalogScope.GLOBAL.value,
                    Program.slug == seed.slug,
                )
                .with_for_update()
            )
            if program is None:
                catalog = AsyncCatalogApplication(
                    self._session,
                    clock=self._clock,
                    allow_technical_validation_publication=(
                        self._environment in {"staging", "test"}
                    ),
                )
                await catalog.create_program(
                    actor=catalog_actor,
                    tenant_id=None,
                    scope=CatalogScope.GLOBAL.value,
                    slug=seed.slug,
                    title=seed.title,
                    program_id=program_id,
                    now=self._clock(),
                )
                program = await self._session.scalar(
                    select(Program).where(Program.id == program_id).with_for_update()
                )
            if program is None:
                raise SeedApplicationError("seed program could not be reloaded")
            if program.id != program_id:
                raise SeedApplicationError(
                    "the existing global slug has a different stable identity"
                )
            if program.title != seed.title:
                raise SeedApplicationError(
                    "the existing global program title differs from reviewed data"
                )

            versions = list(
                (
                    await self._session.scalars(
                        select(ProgramVersion)
                        .where(ProgramVersion.program_id == program.id)
                        .order_by(ProgramVersion.version_number.asc())
                    )
                ).all()
            )
            matching = [
                version for version in versions if version.content_digest == seed.content_digest
            ]
            persisted_version: ProgramVersion | ProgramVersionSnapshot
            if matching:
                matching_version = matching[0]
                self._validate_persisted_provenance(matching_version, seed)
                if len(matching) != 1 or matching[0].status != ProgramVersionStatus.PUBLISHED.value:
                    raise SeedAlreadyApplied(
                        "this content digest already exists but is not the current publishable seed"
                    )
                result_version_id = matching_version.id
                result_version_number = matching_version.version_number
                status = "already_applied"
            else:
                current = next(
                    (
                        version
                        for version in reversed(versions)
                        if version.status == ProgramVersionStatus.PUBLISHED.value
                    ),
                    None,
                )
                version_number = (
                    max((version.version_number for version in versions), default=0) + 1
                )
                version_id = _stable_id("version", seed.content_digest)
                existing_stable_version = next(
                    (version for version in versions if version.id == version_id), None
                )
                if existing_stable_version is not None:
                    raise SeedAlreadyApplied(
                        "the deterministic version identity is already occupied by another snapshot"
                    )
                catalog = AsyncCatalogApplication(
                    self._session,
                    clock=self._clock,
                    allow_technical_validation_publication=(
                        self._environment in {"staging", "test"}
                    ),
                )
                version_snapshot = await catalog.create_version(
                    program.id,
                    actor=catalog_actor,
                    tenant_id=None,
                    version_number=version_number,
                    supersedes_version_id=current.id if current is not None else None,
                    version_id=version_id,
                    content_digest=seed.content_digest,
                    content_source_ref=seed.source_ref,
                    content_reviewed_by=seed.reviewed_by,
                    content_reviewed_at=seed.reviewed_at,
                    release_id=seed.release_id,
                    content_seed_kind=seed.seed_kind,
                    now=self._clock(),
                )
                module_ids: dict[int, UUID] = {}
                for module in seed.modules:
                    module_snapshot = await catalog.add_module(
                        version_snapshot.id,
                        actor=catalog_actor,
                        tenant_id=None,
                        position=module.position,
                        title=module.title,
                        module_id=_stable_id("module", f"{seed.content_digest}:{module.position}"),
                    )
                    module_ids[module.position] = module_snapshot.id
                    for activity in module.activities:
                        await catalog.add_activity(
                            module_snapshot.id,
                            actor=catalog_actor,
                            tenant_id=None,
                            position=activity.position,
                            kind=activity.kind,
                            title=activity.title,
                            prompt=activity.prompt,
                            is_required=activity.is_required,
                            activity_id=_stable_id(
                                "activity",
                                f"{seed.content_digest}:{module.position}:{activity.position}",
                            ),
                        )
                for module in seed.modules:
                    for prerequisite_position in module.prerequisite_positions:
                        await catalog.add_module_prerequisite(
                            module_ids[module.position],
                            module_ids[prerequisite_position],
                            actor=catalog_actor,
                            tenant_id=None,
                            prerequisite_id=_stable_id(
                                "prerequisite",
                                f"{seed.content_digest}:{module.position}:{prerequisite_position}",
                            ),
                        )
                published_version = await catalog.publish_version(
                    version_snapshot.id,
                    actor=catalog_actor,
                    tenant_id=None,
                    now=self._clock(),
                )
                result_version_id = published_version.id
                result_version_number = published_version.version_number
                persisted_version = published_version
                status = "published"

            if matching:
                persisted_version = matching_version

            visible_program_count = int(
                await self._session.scalar(
                    select(func.count())
                    .select_from(Program)
                    .join(ProgramVersion, ProgramVersion.program_id == Program.id)
                    .where(
                        Program.scope == CatalogScope.GLOBAL.value,
                        ProgramVersion.status == ProgramVersionStatus.PUBLISHED.value,
                        ProgramVersion.published_at.is_not(None),
                    )
                )
                or 0
            )
            if visible_program_count == 0:
                raise SeedApplicationError(
                    "seed verification failed: GET /v1/programs would be empty"
                )
            return SeedApplicationResult(
                status=status,
                program_id=program.id,
                program_version_id=result_version_id,
                version_number=result_version_number,
                content_digest=self._required_provenance(
                    persisted_version.content_digest, "content_digest"
                ),
                release_id=self._required_provenance(persisted_version.release_id, "release_id"),
                content_source_ref=self._required_provenance(
                    persisted_version.content_source_ref, "content_source_ref"
                ),
                content_reviewed_by=self._required_provenance(
                    persisted_version.content_reviewed_by, "content_reviewed_by"
                ),
                content_reviewed_at=self._required_provenance(
                    persisted_version.content_reviewed_at, "content_reviewed_at"
                ),
                seed_kind=self._required_provenance(
                    persisted_version.content_seed_kind, "content_seed_kind"
                ),
                visible_program_count=visible_program_count,
            )

    async def _lock_seed_identity(self, seed: FreeCourseSeed) -> None:
        """Serialize all versions of one canonical seed/program on PostgreSQL."""

        bind = self._session.get_bind()
        if bind.dialect.name != "postgresql":
            return
        lock_material = f"{_SEED_LOCK_NAMESPACE}:{seed.seed_kind}:{seed.seed_key}"
        lock_digest = hashlib.sha256(lock_material.encode("utf-8")).digest()
        lock_key = int.from_bytes(lock_digest[:8], byteorder="big", signed=True) or 1
        await self._session.execute(select(func.pg_advisory_xact_lock(lock_key)))

    async def _authorize_seed_actor(self, actor: ActorContext) -> ActorContext:
        """Verify persisted deployment authority; caller-supplied permissions are ignored."""

        person = await self._session.scalar(
            select(Person)
            .where(Person.id == actor.person_id, Person.status == PersonStatus.ACTIVE.value)
            .with_for_update()
        )
        membership = await self._session.scalar(
            select(Membership)
            .join(Tenant, Tenant.id == Membership.tenant_id)
            .where(
                Membership.person_id == actor.person_id,
                Membership.status == MembershipStatus.ACTIVE.value,
                Membership.ended_at.is_(None),
                Membership.role.in_(("admin", "owner")),
                Tenant.status == TenantStatus.ACTIVE.value,
            )
            .with_for_update()
        )
        if person is None or membership is None:
            raise SeedApplicationError(
                "the seed actor must be an existing active person with an active admin "
                "or owner membership"
            )
        return replace(actor, permissions=_SEED_PERMISSIONS)

    @staticmethod
    def _required_provenance(value: _ProvenanceT | None, field: str) -> _ProvenanceT:
        if value is None:
            raise SeedApplicationError(f"persisted seed provenance is missing {field}")
        return value

    @staticmethod
    def _validate_persisted_provenance(
        version: ProgramVersion | ProgramVersionSnapshot, seed: FreeCourseSeed
    ) -> None:
        persisted_reviewed_at = version.content_reviewed_at
        if persisted_reviewed_at is not None and persisted_reviewed_at.tzinfo is None:
            persisted_reviewed_at = persisted_reviewed_at.replace(tzinfo=UTC)
        elif persisted_reviewed_at is not None:
            persisted_reviewed_at = persisted_reviewed_at.astimezone(UTC)
        expected = (
            seed.content_digest,
            seed.source_ref,
            seed.reviewed_by,
            seed.reviewed_at,
            seed.release_id,
            seed.seed_kind,
        )
        actual = (
            version.content_digest,
            version.content_source_ref,
            version.content_reviewed_by,
            persisted_reviewed_at,
            version.release_id,
            version.content_seed_kind,
        )
        if actual != expected:
            raise SeedApplicationError(
                "content digest replay provenance does not match the persisted version"
            )


__all__ = [
    "SeedAlreadyApplied",
    "SeedApplicationError",
    "SeedApplicationResult",
    "StagingSeedApplication",
]
