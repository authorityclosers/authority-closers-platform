"""Audited application import of the fixed, licensed staging playback package.

Run with ``python -m ac_platform.media.staging_fixture_import``. No source URL,
READY state, playback grant, enrollment or caller-supplied media metadata is an
input. This command does not activate the normal upload/provider/webhook paths.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.application.release_identity import ReleaseIdentityError
from ac_platform.application.settings import Settings
from ac_platform.audit import AuditRepository
from ac_platform.audit.models import AuditEvent
from ac_platform.catalog.models import Activity, Program, ProgramVersion
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import DomainError
from ac_platform.media.api_contracts import (
    ActivityMediaBindingRequest,
    ActivityMediaBindingResponse,
)
from ac_platform.media.errors import MediaConfigurationError, MediaConflict, MediaForbidden
from ac_platform.media.models import (
    MediaAsset,
    MediaCaptionTrack,
    MediaLifecycle,
    MediaPurpose,
    MediaRendition,
    MediaVersion,
)
from ac_platform.media.processing import ProcessingQuota
from ac_platform.media.scanner import SignatureContentScanner
from ac_platform.media.service import MediaService
from ac_platform.media.signing import MediaSigner
from ac_platform.media.staging_fixture_manifest import (
    MANIFEST_SHA256,
    REGISTRY_SHA256,
    VerifiedFixtureProcessor,
    VerifiedStagingFixturePack,
    load_verified_staging_fixture_pack,
    require_staging_scope,
)
from ac_platform.seed.application import (
    SeedApplicationError,
    SeedApplicationResult,
    StagingSeedApplication,
)
from ac_platform.seed.technical_media_fixture_v2 import (
    FILM_ACTIVITY_PROMPTS,
    FILM_ACTIVITY_TITLES,
    technical_media_identity,
    technical_media_seed,
)
from ac_platform.tenancy.models import Membership, Tenant


@dataclass(frozen=True, slots=True)
class StagingFixtureImportResult:
    status: str
    tenant_id: UUID
    catalog_version_id: UUID
    release_id: str
    manifest_sha256: str
    binding_ids: tuple[UUID, ...]
    media_version_ids: tuple[UUID, ...]


class StagingFixtureImportApplication:
    """One explicit package, tenant and published technical catalog version."""

    def __init__(
        self,
        database: AsyncSession,
        *,
        environment: str,
        release_id: str,
        pack: VerifiedStagingFixturePack,
    ) -> None:
        require_staging_scope(environment, release_id)
        if not isinstance(pack, VerifiedStagingFixturePack):
            raise MediaConfigurationError("A verified public-film package is required.")
        pack.require_scope(environment=environment, release_id=release_id, tenant_id=pack.tenant_id)
        self.database = database
        self.environment = environment
        self.release_id = release_id
        self.pack = pack
        # No token is issued by this application. These ephemeral, unexposed
        # keys satisfy the existing service interface, not runtime activation.
        self.service = MediaService(
            storage=pack.storage,
            signer=MediaSigner(secrets.token_bytes(32)),
            webhook_secret=secrets.token_bytes(32),
            scanner=SignatureContentScanner(),
            processor=VerifiedFixtureProcessor(pack),
            processing_quota=ProcessingQuota(
                max_source_bytes=128 * 1024**2,
                max_output_bytes=256 * 1024**2,
                max_duration_seconds=13,
                max_head_operations=256,
            ),
        )

    async def _authorize(self, actor_person_id: UUID) -> ActorContext:
        member = await self.database.scalar(
            select(Membership)
            .join(Person, Person.id == Membership.person_id)
            .join(Tenant, Tenant.id == Membership.tenant_id)
            .where(
                Membership.tenant_id == self.pack.tenant_id,
                Membership.person_id == actor_person_id,
                Membership.role.in_(("admin", "owner")),
                Membership.status == "active",
                Membership.ended_at.is_(None),
                Tenant.status == "active",
                Person.status == "active",
            )
            .with_for_update()
        )
        if member is None:
            raise MediaForbidden(
                "An active administrator in the exact existing tenant is required."
            )
        return ActorContext(
            actor_person_id, uuid4(), self.pack.tenant_id, permissions=frozenset({"catalog_write"})
        )

    async def _catalog(self, expected_catalog_version_id: UUID) -> None:
        seed = technical_media_seed(self.release_id)
        program_id, version_id, module_id, activity_ids = technical_media_identity(self.release_id)
        if expected_catalog_version_id != version_id:
            raise MediaForbidden(
                "Only the package-owned technical-media catalog version is allowed."
            )
        row = await self.database.scalar(
            select(ProgramVersion)
            .join(Program, Program.id == ProgramVersion.program_id)
            .where(
                ProgramVersion.id == version_id,
                ProgramVersion.program_id == program_id,
                ProgramVersion.scope == "global",
                ProgramVersion.owner_key == UUID(int=0),
                ProgramVersion.tenant_id.is_(None),
                ProgramVersion.status == "published",
                Program.slug == seed.slug,
                Program.title == seed.title,
                Program.scope == "global",
                Program.owner_key == UUID(int=0),
            )
            .with_for_update()
        )
        if row is None:
            raise MediaForbidden("The exact published technical-media catalog version is required.")
        StagingSeedApplication._validate_persisted_provenance(row, seed)
        rows = tuple(
            (
                await self.database.scalars(
                    select(Activity)
                    .where(
                        Activity.id.in_(activity_ids),
                        Activity.module_id == module_id,
                        Activity.program_version_id == version_id,
                        Activity.program_id == program_id,
                        Activity.scope == "global",
                        Activity.owner_key == UUID(int=0),
                        Activity.tenant_id.is_(None),
                        Activity.kind == "VIDEO",
                    )
                    .order_by(Activity.position)
                )
            ).all()
        )
        if tuple(item.id for item in rows) != activity_ids or any(
            (row.title, row.prompt) != (FILM_ACTIVITY_TITLES[index], FILM_ACTIVITY_PROMPTS[index])
            for index, row in enumerate(rows)
        ):
            raise MediaForbidden(
                "The two explicitly labeled technical film activities are required."
            )

    def _materialize(
        self,
        database: Session,
        actor: ActorContext,
        *,
        replay: bool,
    ) -> tuple[ActivityMediaBindingResponse, ...]:
        program_id, catalog_version, module_id, activities = technical_media_identity(
            self.release_id
        )
        results: list[ActivityMediaBindingResponse] = []
        for index, clip in enumerate(self.pack.clips):
            existing = database.scalar(
                select(MediaVersion).where(MediaVersion.id == clip.version_id)
            )
            if (existing is not None) != replay:
                raise MediaConflict(
                    "Fixture import history is incomplete or the identity is occupied."
                )
            version = self.service.register_verified_staging_fixture_source(
                database,
                actor,
                self.pack,
                clip.spec.fixture_id,
                environment=self.environment,
                release_id=self.release_id,
            )
            if replay:
                if version.state != MediaLifecycle.READY.value or (
                    version.duration_seconds != clip.spec.duration_seconds
                    or version.width != clip.spec.width
                    or version.height != clip.spec.height
                ):
                    raise MediaConflict("The imported fixture version changed after approval.")
                asset = database.get(MediaAsset, clip.asset_id)
                if asset is None or asset.current_version_id != version.id:
                    raise MediaConflict("The imported fixture asset is no longer current.")
                renditions = database.scalars(
                    select(MediaRendition).where(
                        MediaRendition.tenant_id == self.pack.tenant_id,
                        MediaRendition.version_id == version.id,
                    )
                ).all()
                expected_renditions = {
                    (
                        item.id,
                        item.protocol,
                        item.content_type,
                        item.object_key,
                        item.width,
                        item.height,
                        item.bitrate_kbps,
                    )
                    for item in clip.processing_result.renditions
                }
                if {
                    (
                        item.id,
                        item.protocol,
                        item.content_type,
                        item.object_key,
                        item.width,
                        item.height,
                        item.bitrate_kbps,
                    )
                    for item in renditions
                } != expected_renditions:
                    raise MediaConflict("The imported fixture rendition inventory changed.")
                captions = database.scalars(
                    select(MediaCaptionTrack).where(
                        MediaCaptionTrack.tenant_id == self.pack.tenant_id,
                        MediaCaptionTrack.version_id == version.id,
                    )
                ).all()
                if {
                    (
                        item.id,
                        item.language,
                        item.kind,
                        item.content_type,
                        item.object_key,
                        item.is_default,
                        item.state,
                    )
                    for item in captions
                } != {
                    (
                        item.id,
                        item.language,
                        item.kind,
                        item.content_type,
                        item.object_key,
                        item.is_default,
                        "ready",
                    )
                    for item in clip.processing_result.captions
                }:
                    raise MediaConflict("The imported fixture caption inventory changed.")
            else:
                self.service.process_version(database, actor, version.id)
            result = self.service.bind_activity_media(
                database,
                actor,
                ActivityMediaBindingRequest(
                    activity_id=activities[index],
                    module_id=module_id,
                    program_version_id=catalog_version,
                    program_id=program_id,
                    program_scope="global",
                    program_owner_key=UUID(int=0),
                    asset_id=clip.asset_id,
                    version_id=clip.version_id,
                    approval_reference=f"AC-ALPHA-PUBLIC-FILMS:{self.pack.manifest_sha256}",
                ),
                idempotency_key=f"staging-fixture:{self.pack.manifest_sha256}:{clip.spec.fixture_id}",
            )
            if result.state != "approved":
                raise MediaConflict("The imported fixture binding is no longer approved.")
            results.append(result)
        return tuple(results)

    async def apply(
        self,
        *,
        actor_person_id: UUID,
        expected_catalog_version_id: UUID,
    ) -> StagingFixtureImportResult:
        self.pack.require_scope(
            environment=self.environment, release_id=self.release_id, tenant_id=self.pack.tenant_id
        )
        # Repeat all bounded source/probe/HLS validation before opening any DB
        # transaction. The service repeats identity/processing checks inside it.
        processor = VerifiedFixtureProcessor(self.pack)
        for clip in self.pack.clips:
            processor.process(
                storage=self.pack.storage,
                version_id=clip.version_id,
                purpose=MediaPurpose.VIDEO,
                source_key=clip.source_key,
                content_type="video/mp4",
                crop=None,
            )
        async with self.database.begin():
            actor = await self._authorize(actor_person_id)
            await self._catalog(expected_catalog_version_id)
            # The exact tenant membership lock serializes this operator's
            # imports; the PostgreSQL advisory lock covers different admins.
            if self.database.get_bind().dialect.name == "postgresql":
                lock_key = int.from_bytes(self.pack.tenant_id.bytes[:8], "big", signed=True)
                await self.database.execute(select(func.pg_advisory_xact_lock(lock_key)))
            audit = await self.database.scalar(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == self.pack.tenant_id,
                    AuditEvent.action == "media.staging_public_fixtures_imported",
                    AuditEvent.resource_type == "media_fixture_import",
                    AuditEvent.resource_id == self.pack.manifest_sha256,
                )
            )
            replay = audit is not None
            if audit is not None and (
                audit.actor_person_id != actor_person_id
                or audit.payload.get("release_id") != self.release_id
                or audit.payload.get("catalog_version_id") != str(expected_catalog_version_id)
                or audit.payload.get("manifest_sha256") != self.pack.manifest_sha256
            ):
                raise MediaConflict(
                    "Fixture import replay does not match its immutable audit record."
                )
            bindings = await self.database.run_sync(
                lambda database: self._materialize(
                    database,
                    actor,
                    replay=replay,
                )
            )
            binding_ids = tuple(item.id for item in bindings)
            if audit is not None:
                if audit.payload.get("binding_ids") != [str(value) for value in binding_ids]:
                    raise MediaConflict(
                        "The fixture binding identities differ from the import audit."
                    )
            else:
                await AuditRepository(self.database).append(
                    tenant_id=self.pack.tenant_id,
                    actor_person_id=actor_person_id,
                    session_id=None,
                    actor_type="person",
                    action="media.staging_public_fixtures_imported",
                    resource_type="media_fixture_import",
                    resource_id=self.pack.manifest_sha256,
                    payload={
                        "manifest_sha256": self.pack.manifest_sha256,
                        "fixture_registry_sha256": REGISTRY_SHA256,
                        "release_id": self.release_id,
                        "catalog_version_id": str(expected_catalog_version_id),
                        "binding_ids": [str(value) for value in binding_ids],
                        "fixture_ids": [item.spec.fixture_id for item in self.pack.clips],
                        "media_version_ids": [str(item.version_id) for item in self.pack.clips],
                        "course_content": False,
                    },
                    reason="User-authorized staging-only licensed public-film player validation",
                    request_id=f"staging-films:{self.pack.manifest_sha256}",
                    now=datetime.now(UTC),
                )
            return StagingFixtureImportResult(
                "already_imported" if replay else "imported",
                self.pack.tenant_id,
                expected_catalog_version_id,
                self.release_id,
                self.pack.manifest_sha256,
                binding_ids,
                tuple(item.version_id for item in self.pack.clips),
            )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actor-person-id", type=UUID, required=True)
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--catalog-version-id", type=UUID)
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--publish-catalog", action="store_true")
    parser.add_argument("--acknowledge-staging-public-film-tests", action="store_true")
    return parser


class _TenantStagingSeedApplication(StagingSeedApplication):
    """Retain canonical seed commands; constrain their actor to the named tenant."""

    def __init__(
        self, database: AsyncSession, *, tenant_id: UUID, release_id: str, environment: str
    ) -> None:
        super().__init__(database, environment=environment, expected_release_id=release_id)
        self.tenant_id = tenant_id

    async def _authorize_seed_actor(self, actor: ActorContext) -> ActorContext:
        member = await self._session.scalar(
            select(Membership)
            .join(
                Person,
                Person.id == Membership.person_id,
            )
            .join(Tenant, Tenant.id == Membership.tenant_id)
            .where(
                Membership.tenant_id == self.tenant_id,
                Membership.person_id == actor.person_id,
                Membership.role.in_(("admin", "owner")),
                Membership.status == "active",
                Membership.ended_at.is_(None),
                Person.status == "active",
                Tenant.status == "active",
            )
            .with_for_update()
        )
        if member is None:
            raise MediaForbidden("The existing tenant administrator is required.")
        return await super()._authorize_seed_actor(actor)


async def _run(args: argparse.Namespace) -> int:
    environment = os.getenv("AC_ENVIRONMENT", "").strip().lower()
    require_staging_scope(environment, args.release_id)
    if environment != "staging" or not args.acknowledge_staging_public_film_tests:
        raise MediaForbidden("The CLI requires staging and explicit public-film acknowledgement.")
    if os.getenv("AC_RELEASE_ID") != args.release_id:
        raise MediaForbidden("The CLI release must match the deployed release identity.")
    settings = Settings(environment="staging", release_id=args.release_id)
    if settings.public_learner_tenant_id != args.tenant_id:
        raise MediaForbidden(
            "Only the configured existing learner tenant may receive this package."
        )
    if not args.publish_catalog and (
        args.catalog_version_id is None
        or args.manifest_sha256 != MANIFEST_SHA256
        or not settings.media_stress_fixtures_enabled
        or not settings.media_stress_fixtures_cache_root
    ):
        raise MediaForbidden(
            "Import requires the exact catalog, manifest and explicit fixture root."
        )
    # All filesystem verification precedes engine creation. Publishing catalog
    # content alone requires no media files or provider activation.
    pack = (
        None
        if args.publish_catalog
        else load_verified_staging_fixture_pack(
            environment=environment,
            release_id=args.release_id,
            tenant_id=args.tenant_id,
            root=Path(settings.media_stress_fixtures_cache_root or ""),
            expected_manifest_sha256=args.manifest_sha256,
        )
    )
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as database:
            result: SeedApplicationResult | StagingFixtureImportResult
            if args.publish_catalog:
                result = await _TenantStagingSeedApplication(
                    database,
                    environment=environment,
                    release_id=args.release_id,
                    tenant_id=args.tenant_id,
                ).apply_technical_validation(
                    technical_media_seed(args.release_id),
                    actor=ActorContext(args.actor_person_id, uuid4(), None),
                )
            else:
                if pack is None:
                    raise MediaForbidden("The verified fixture package is unavailable.")
                result = await StagingFixtureImportApplication(
                    database,
                    environment=environment,
                    release_id=args.release_id,
                    pack=pack,
                ).apply(
                    actor_person_id=args.actor_person_id,
                    expected_catalog_version_id=args.catalog_version_id,
                )
    finally:
        await engine.dispose()
    print(json.dumps(asdict(result), default=str, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return run_async(_run(args))
    except (DomainError, ValueError, OSError, SeedApplicationError, ReleaseIdentityError):
        print(
            "staging fixture import refused: scope, approval or artifact validation failed",
            file=sys.stderr,
        )
        return 2
    except SQLAlchemyError:
        print("staging fixture import refused: database operation failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
