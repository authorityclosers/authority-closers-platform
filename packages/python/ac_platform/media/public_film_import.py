"""Canonical, explicitly reviewed public-film demonstration import.

The caller owns the transaction and supplies a real opaque operator session.
This module neither enrolls learners nor enables a Watch completion policy.
The fixed catalog is not an instructional or general-purpose upload facility.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction, SessionTransactionOrigin

from ac_platform.audit import AuditRepository
from ac_platform.audit.models import AuditEvent
from ac_platform.authorization.models import CapabilityGrant, CapabilityRevocation
from ac_platform.authorization.studio import LEGACY_STUDIO_PERMISSIONS, StudioAuthorization
from ac_platform.catalog.content import (
    CanonicalActivityContent,
    CanonicalModuleContent,
    canonical_catalog_content_digest,
)
from ac_platform.catalog.models import Activity, Module, ModulePrerequisite, Program, ProgramVersion
from ac_platform.catalog.services import AsyncCatalogApplication
from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.media.api_contracts import (
    ActivityMediaBindingRequest,
    ActivityMediaBindingResponse,
)
from ac_platform.media.errors import MediaConflict, MediaForbidden
from ac_platform.media.models import (
    ActivityMediaBinding,
    MediaAsset,
    MediaCaptionTrack,
    MediaPurpose,
    MediaRendition,
    MediaVersion,
)
from ac_platform.media.processing import ProcessingQuota
from ac_platform.media.public_film_manifest import (
    VerifiedPublicFilmPack,
    VerifiedPublicFilmProcessor,
)
from ac_platform.media.scanner import SignatureContentScanner
from ac_platform.media.service import MediaService
from ac_platform.media.signing import MediaSigner
from ac_platform.tenancy.models import Membership, Tenant

_NAMESPACE = UUID("9df24a04-abcf-58aa-99f8-3f3ca415b631")
_SEAL = object()
_ACTION = "media.public_films_imported.v1"
_RESOURCE = "public_film_import"
_PERMISSIONS = frozenset({"catalog_write", "catalog_publish"})
_FIXTURES = ("bbb-4k-30-normal", "caminandes-gran-dillama-1080p")


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class PublicFilmCatalogSpec:
    tenant_id: UUID
    manifest_sha256: str
    program_id: UUID
    program_version_id: UUID
    module_id: UUID
    activity_ids: tuple[UUID, ...]
    slug: str
    title: str
    module_title: str
    activity_titles: tuple[str, ...]
    activity_prompts: tuple[str, ...]
    content_digest: str
    source_ref: str

    def matches_catalog(self, activity: object, version: object) -> bool:
        """Exact catalog identity/content; approval release is immutable, not today's release."""
        identifier = getattr(activity, "id", None)
        if identifier not in self.activity_ids:
            return False
        position = self.activity_ids.index(identifier)
        return (
            all(
                getattr(activity, name, None) == expected
                for name, expected in {
                    "scope": "tenant",
                    "owner_key": self.tenant_id,
                    "tenant_id": self.tenant_id,
                    "program_id": self.program_id,
                    "program_version_id": self.program_version_id,
                    "module_id": self.module_id,
                    "position": position + 1,
                    "kind": "VIDEO",
                    "title": self.activity_titles[position],
                    "prompt": self.activity_prompts[position],
                    "is_required": False,
                }.items()
            )
            and all(
                getattr(version, name, None) == expected
                for name, expected in {
                    "id": self.program_version_id,
                    "program_id": self.program_id,
                    "scope": "tenant",
                    "owner_key": self.tenant_id,
                    "tenant_id": self.tenant_id,
                    "version_number": 1,
                    "content_digest": self.content_digest,
                    "content_source_ref": self.source_ref,
                    "content_seed_kind": "reviewed",
                    "supersedes_version_id": None,
                }.items()
            )
            and (
                getattr(version, "status", None) in {"published", "superseded"}
                and re.fullmatch(
                    r"person:[0-9a-f-]{36}", str(getattr(version, "content_reviewed_by", ""))
                )
                is not None
                and isinstance(getattr(version, "content_reviewed_at", None), datetime)
                and re.fullmatch(r"[0-9a-f]{40}", str(getattr(version, "release_id", "")))
                is not None
            )
        )


def public_film_catalog(pack: VerifiedPublicFilmPack) -> PublicFilmCatalogSpec:
    if type(pack) is not VerifiedPublicFilmPack:
        raise MediaForbidden("The sealed public-film package is required.")
    pack.require_scope(
        environment=pack.environment, release_id=pack.release_id, tenant_id=pack.tenant_id
    )
    if tuple(clip.spec.fixture_id for clip in pack.clips) != _FIXTURES:
        raise MediaForbidden("Only the two approved demonstration clips are supported.")
    prefix = f"{pack.tenant_id}:{pack.manifest_sha256}"

    def identity(name: str) -> UUID:
        return uuid5(_NAMESPACE, f"{prefix}:{name}")

    title = "Public-film playback demonstrations — not Dipak instruction"
    module_title = "Optional licensed 12-second playback demonstrations"
    titles = (
        "Big Buck Bunny — licensed 12-second 4K demonstration",
        "Caminandes 2 — licensed 12-second 1080p demonstration",
    )
    prompts = tuple(
        "PUBLIC-FILM DEMONSTRATION — 12-second excerpt, not Dipak instruction. "
        f"{clip.provenance.title}. Credits: {clip.provenance.attribution}. "
        f"License: {clip.provenance.license} {clip.provenance.license_url} . "
        f"Official source: {clip.provenance.source_page} . {clip.provenance.modifications}"
        for clip in pack.clips
    )
    slug = f"public-film-demo-{pack.manifest_sha256[:16]}"
    digest = canonical_catalog_content_digest(
        program_slug=slug,
        program_title=title,
        modules=(
            CanonicalModuleContent(
                position=1,
                title=module_title,
                prerequisite_positions=(),
                activities=tuple(
                    CanonicalActivityContent(
                        position=index + 1,
                        kind="VIDEO",
                        title=titles[index],
                        is_required=False,
                        prompt=prompts[index],
                    )
                    for index in range(2)
                ),
            ),
        ),
    )
    return PublicFilmCatalogSpec(
        pack.tenant_id,
        pack.manifest_sha256,
        identity("program"),
        identity("version"),
        identity("module"),
        tuple(identity(f"activity:{name}") for name in _FIXTURES),
        slug,
        title,
        module_title,
        titles,
        prompts,
        digest,
        f"package:ac_platform.media.public_film_manifest:{pack.manifest_sha256}",
    )


@dataclass(frozen=True, slots=True)
class PublicFilmImportAuthorization:
    """Private transaction lease, never a client claim or modified ActorContext.

    Canonical Studio authorization issues the lease. Each synchronous lifecycle
    use additionally rechecks persisted identity and the exact two tenant-wide
    rights, including changes/revocations made earlier in this transaction.
    """

    database: Session = field(repr=False)
    transaction: SessionTransaction = field(repr=False)
    savepoint: SessionTransaction = field(repr=False)
    service: MediaService = field(repr=False)
    processor: object = field(repr=False)
    actor: ActorContext = field(repr=False)
    pack: VerifiedPublicFilmPack = field(repr=False)
    catalog: PublicFilmCatalogSpec
    _seal: object = field(repr=False)

    def require(
        self,
        database: Session,
        actor: ActorContext,
        *,
        version_id: UUID,
        service: MediaService,
        request: ActivityMediaBindingRequest | None = None,
    ) -> None:
        if (
            type(self) is not PublicFilmImportAuthorization
            or self._seal is not _SEAL
            or database is not self.database
            or database.get_transaction() is not self.transaction
            or database.get_nested_transaction() is not self.savepoint
            or not self.savepoint.is_active
            or service is not self.service
            or service.storage is not self.pack.storage
            or service.processor is not self.processor
            or not self.transaction.is_active
            or actor != self.actor
            or actor.tenant_id != self.pack.tenant_id
            or version_id not in {clip.version_id for clip in self.pack.clips}
        ):
            raise MediaForbidden("The exact active public-film import transaction is required.")
        self.pack.require_scope(
            environment=self.pack.environment,
            release_id=self.pack.release_id,
            tenant_id=actor.tenant_id,
        )
        clip = next(clip for clip in self.pack.clips if clip.version_id == version_id)
        if request is not None:
            index = self.pack.clips.index(clip)
            expected = (
                self.catalog.activity_ids[index],
                self.catalog.module_id,
                self.catalog.program_version_id,
                self.catalog.program_id,
                "tenant",
                self.pack.tenant_id,
                clip.asset_id,
                clip.version_id,
                f"PUBLIC-FILM-DEMO:{self.pack.manifest_sha256}",
                None,
                None,
            )
            if (
                request.activity_id,
                request.module_id,
                request.program_version_id,
                request.program_id,
                request.program_scope,
                request.program_owner_key,
                request.asset_id,
                request.version_id,
                request.approval_reference,
                request.activity_version,
                request.supersedes_binding_id,
            ) != expected:
                raise MediaForbidden("The binding is outside the exact public-film package.")
        person = database.scalar(
            select(Person)
            .where(Person.id == actor.person_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        session = database.scalar(
            select(IdentitySession)
            .where(IdentitySession.id == actor.session_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        tenant = database.scalar(
            select(Tenant)
            .where(Tenant.id == actor.tenant_id)
            .execution_options(populate_existing=True)
            .with_for_update(read=True)
        )
        member = database.scalar(
            select(Membership)
            .where(
                Membership.person_id == actor.person_id,
                Membership.tenant_id == actor.tenant_id,
            )
            .execution_options(populate_existing=True)
            .with_for_update(read=True)
        )
        if (
            person is None
            or person.status != "active"
            or person.email_verified_at is None
            or session is None
            or session.person_id != actor.person_id
            or session.selected_tenant_id != actor.tenant_id
            or session.revoked_at is not None
            or _utc(session.expires_at) <= datetime.now(UTC)
            or tenant is None
            or tenant.status != "active"
            or member is None
            or member.status != "active"
            or member.ended_at is not None
            or member.role not in {"owner", "admin", "support", "learner"}
        ):
            raise MediaForbidden("The canonical public-film operator session is unavailable.")
        legacy = actor.permissions & LEGACY_STUDIO_PERMISSIONS.get(member.role, frozenset())
        assigned = set(
            database.scalars(
                select(CapabilityGrant.permission).where(
                    CapabilityGrant.subject_person_id == actor.person_id,
                    CapabilityGrant.tenant_id == actor.tenant_id,
                    CapabilityGrant.scope_kind == "tenant",
                    CapabilityGrant.program_id.is_(None),
                    CapabilityGrant.permission.in_(_PERMISSIONS),
                    ~exists().where(CapabilityRevocation.grant_id == CapabilityGrant.id),
                )
            )
        )
        if not legacy | assigned >= _PERMISSIONS:
            raise MediaForbidden(
                "Current academy-wide authoring and publication rights are required."
            )


@dataclass(frozen=True, slots=True)
class PublicFilmImportResult:
    status: str
    command_id: UUID
    tenant_id: UUID
    program_id: UUID
    program_version_id: UUID
    manifest_sha256: str
    binding_ids: tuple[UUID, ...]
    media_version_ids: tuple[UUID, ...]


class PublicFilmImportApplication:
    def __init__(
        self,
        database: AsyncSession,
        *,
        token_pepper: bytes | str,
        environment: str,
        release_id: str,
        pack: VerifiedPublicFilmPack,
    ) -> None:
        if type(pack) is not VerifiedPublicFilmPack:
            raise MediaForbidden("The sealed public-film package is required.")
        pack.require_scope(environment=environment, release_id=release_id, tenant_id=pack.tenant_id)
        self.database = database
        self.identity = AsyncIdentityApplication(database, token_pepper=token_pepper)
        self.pack = pack
        self.catalog = public_film_catalog(pack)
        self.service = MediaService(
            storage=pack.storage,
            signer=MediaSigner(secrets.token_bytes(32)),
            webhook_secret=secrets.token_bytes(32),
            scanner=SignatureContentScanner(),
            processor=VerifiedPublicFilmProcessor(pack),
            processing_quota=ProcessingQuota(
                max_source_bytes=128 * 1024**2,
                max_output_bytes=256 * 1024**2,
                max_duration_seconds=13,
                max_head_operations=256,
            ),
        )

    async def _authorize(self, actor: ActorContext) -> None:
        if actor.tenant_id != self.pack.tenant_id:
            raise MediaForbidden("The session must select the exact package academy.")
        authorization = StudioAuthorization(self.database)
        for permission in sorted(_PERMISSIONS):
            await authorization.require(actor, permission)

    async def apply(
        self,
        *,
        session_token: str,
        command_id: UUID,
        expected_program_version_id: UUID,
        reason: str,
    ) -> PublicFilmImportResult:
        """Return an uncommitted result; the caller must commit before publishing success."""
        transaction = self.database.get_transaction()
        if (
            transaction is None
            or transaction.sync_transaction is None
            or transaction.sync_transaction.origin is not SessionTransactionOrigin.BEGIN
        ):
            raise MediaForbidden("Public-film import requires a caller-owned transaction.")
        if (
            type(command_id) is not UUID
            or command_id.int == 0
            or expected_program_version_id != self.catalog.program_version_id
            or not isinstance(reason, str)
            or not reason.strip()
            or reason != reason.strip()
            or len(reason) > 500
            or any(ord(c) < 32 or ord(c) == 127 for c in reason)
            or not isinstance(session_token, str)
            or re.fullmatch(r"[A-Za-z0-9_-]{43,512}", session_token) is None
        ):
            raise MediaForbidden("An exact, bounded public-film approval intent is required.")
        self.pack.require_scope(
            environment=self.pack.environment,
            release_id=self.pack.release_id,
            tenant_id=self.pack.tenant_id,
        )
        for clip in self.pack.clips:
            VerifiedPublicFilmProcessor(self.pack).process(
                storage=self.pack.storage,
                version_id=clip.version_id,
                purpose=MediaPurpose.VIDEO,
                source_key=clip.source_key,
                content_type="video/mp4",
                crop=None,
            )
        # A separate import savepoint makes an intercepted failure atomic too.
        async with self.database.begin_nested():
            if self.database.get_bind().dialect.name == "postgresql":
                key = int.from_bytes(
                    hashlib.sha256(b"ac.public-film-import.v1").digest()[:8], "big", signed=True
                )
                await self.database.execute(select(func.pg_advisory_xact_lock(key)))
            # Reuse normal HTTP authentication's existing server-owned role
            # projection. Explicit grants are never merged into actor permissions.
            from ac_platform.http.auth import _with_role_permissions

            actor = _with_role_permissions(
                await self.identity.resolve_actor(session_token, require_tenant=True)
            ).actor
            await self._authorize(actor)

            def mint(database: Session) -> PublicFilmImportAuthorization:
                root, savepoint = database.get_transaction(), database.get_nested_transaction()
                if root is None or savepoint is None:
                    raise MediaForbidden("The import authorization transaction is unavailable.")
                return PublicFilmImportAuthorization(
                    database,
                    root,
                    savepoint,
                    self.service,
                    self.service.processor,
                    actor,
                    self.pack,
                    self.catalog,
                    _SEAL,
                )

            lease = await self.database.run_sync(mint)
            intent: dict[str, Any] = {
                "manifest_sha256": self.pack.manifest_sha256,
                "release_id": self.pack.release_id,
                "environment": self.pack.environment,
                "program_id": str(self.catalog.program_id),
                "program_version_id": str(self.catalog.program_version_id),
                "content_digest": self.catalog.content_digest,
                "course_content": False,
                "watch_completion_enabled": False,
            }
            prior = await self.database.scalar(
                select(AuditEvent).where(AuditEvent.id == command_id)
            )
            replay = prior is not None
            if prior is not None and (
                prior.tenant_id != self.pack.tenant_id
                or prior.actor_person_id != actor.person_id
                or prior.action != _ACTION
                or prior.resource_type != _RESOURCE
                or prior.resource_id != self.pack.manifest_sha256
                or prior.reason != reason
                or {key: prior.payload.get(key) for key in intent} != intent
            ):
                raise MediaConflict("The command identity belongs to another immutable approval.")
            reviewed_at = datetime.now(UTC)
            if not replay:
                await self._create_catalog(actor, reviewed_at)
            elif prior is not None:
                await self._validate_catalog(actor, prior)
            # Activity precedes media asset/version locks in ordinary binding commands.
            await self.database.scalars(
                select(Activity)
                .where(
                    Activity.id.in_(self.catalog.activity_ids),
                    Activity.tenant_id == self.pack.tenant_id,
                )
                .order_by(Activity.id)
                .with_for_update()
            )
            for clip in self.pack.clips:
                await self._authorize(actor)
                fixture_id = clip.spec.fixture_id

                def materialize(database: Session, name: str = fixture_id) -> None:
                    self._source(database, actor, lease, name, replay=replay)

                await self.database.run_sync(materialize)
            if not replay:
                await self._authorize(actor)
                await AsyncCatalogApplication(self.database).publish_version(
                    self.catalog.program_version_id,
                    actor=actor,
                    tenant_id=self.pack.tenant_id,
                )
            await self._authorize(actor)
            bindings = await self.database.run_sync(
                lambda database: self._bind(
                    database,
                    actor,
                    lease,
                    replay=replay,
                )
            )
            binding_ids = tuple(binding.id for binding in bindings)
            if replay:
                if prior is None or prior.payload.get("binding_ids") != [
                    str(item) for item in binding_ids
                ]:
                    raise MediaConflict("The binding history no longer matches the approval.")
            else:
                await AuditRepository(self.database).append(
                    tenant_id=self.pack.tenant_id,
                    actor_person_id=actor.person_id,
                    session_id=actor.session_id,
                    event_id=command_id,
                    action=_ACTION,
                    resource_type=_RESOURCE,
                    resource_id=self.pack.manifest_sha256,
                    payload={
                        **intent,
                        "binding_ids": [str(item) for item in binding_ids],
                        "media_version_ids": [str(clip.version_id) for clip in self.pack.clips],
                    },
                    reason=reason,
                    request_id=f"public-films:{command_id}",
                    now=reviewed_at,
                )
            return PublicFilmImportResult(
                "already_imported" if replay else "imported",
                command_id,
                self.pack.tenant_id,
                self.catalog.program_id,
                self.catalog.program_version_id,
                self.pack.manifest_sha256,
                binding_ids,
                tuple(clip.version_id for clip in self.pack.clips),
            )

    async def _create_catalog(self, actor: ActorContext, reviewed_at: datetime) -> None:
        spec = self.catalog
        app = AsyncCatalogApplication(self.database)
        await app.create_program(
            actor=actor,
            tenant_id=spec.tenant_id,
            slug=spec.slug,
            title=spec.title,
            scope="tenant",
            program_id=spec.program_id,
        )
        await app.create_version(
            spec.program_id,
            actor=actor,
            tenant_id=spec.tenant_id,
            version_number=1,
            version_id=spec.program_version_id,
            content_digest=spec.content_digest,
            content_source_ref=spec.source_ref,
            content_reviewed_by=f"person:{actor.person_id}",
            content_reviewed_at=reviewed_at,
            release_id=self.pack.release_id,
            content_seed_kind="reviewed",
        )
        await app.add_module(
            spec.program_version_id,
            actor=actor,
            tenant_id=spec.tenant_id,
            title=spec.module_title,
            position=1,
            module_id=spec.module_id,
        )
        for index, activity_id in enumerate(spec.activity_ids):
            await app.add_activity(
                spec.module_id,
                actor=actor,
                tenant_id=spec.tenant_id,
                kind="VIDEO",
                title=spec.activity_titles[index],
                prompt=spec.activity_prompts[index],
                position=index + 1,
                activity_id=activity_id,
                is_required=False,
            )

    async def _validate_catalog(self, actor: ActorContext, prior: AuditEvent) -> None:
        spec = self.catalog
        program = await self.database.scalar(select(Program).where(Program.id == spec.program_id))
        version = await self.database.scalar(
            select(ProgramVersion).where(ProgramVersion.id == spec.program_version_id)
        )
        modules = tuple(
            await self.database.scalars(
                select(Module).where(Module.program_version_id == spec.program_version_id)
            )
        )
        activities = tuple(
            await self.database.scalars(
                select(Activity)
                .where(Activity.program_version_id == spec.program_version_id)
                .order_by(Activity.position)
            )
        )
        prerequisites = await self.database.scalar(
            select(ModulePrerequisite.id).where(
                ModulePrerequisite.program_version_id == spec.program_version_id
            )
        )
        if (
            program is None
            or program.tenant_id != spec.tenant_id
            or program.scope != "tenant"
            or program.owner_key != spec.tenant_id
            or program.slug != spec.slug
            or program.title != spec.title
            or version is None
            or version.content_reviewed_by != f"person:{actor.person_id}"
            or version.content_reviewed_at is None
            or _utc(version.content_reviewed_at) != _utc(prior.occurred_at)
            or version.release_id != prior.payload.get("release_id")
            or len(modules) != 1
            or modules[0].id != spec.module_id
            or modules[0].title != spec.module_title
            or modules[0].position != 1
            or modules[0].program_id != spec.program_id
            or modules[0].scope != "tenant"
            or modules[0].tenant_id != spec.tenant_id
            or modules[0].owner_key != spec.tenant_id
            or prerequisites is not None
            or tuple(activity.id for activity in activities) != spec.activity_ids
            or any(not spec.matches_catalog(activity, version) for activity in activities)
        ):
            raise MediaConflict(
                "The approved public-film catalog changed; replay cannot repair it."
            )

    def _source(
        self,
        database: Session,
        actor: ActorContext,
        lease: PublicFilmImportAuthorization,
        fixture_id: str,
        *,
        replay: bool,
    ) -> None:
        clip = next(clip for clip in self.pack.clips if clip.spec.fixture_id == fixture_id)
        existing = database.scalar(select(MediaVersion).where(MediaVersion.id == clip.version_id))
        if (existing is not None) != replay:
            raise MediaConflict("The public-film source identity is occupied or incomplete.")
        version = self.service.register_verified_public_film_source(
            database,
            actor,
            self.pack,
            fixture_id,
            public_film_authorization=lease,
        )
        if not replay:
            self.service.process_version(
                database, actor, version.id, public_film_authorization=lease
            )
            return
        asset = database.get(MediaAsset, clip.asset_id)
        if (
            version.state != "ready"
            or version.duration_seconds != clip.spec.duration_seconds
            or version.width != clip.spec.width
            or version.height != clip.spec.height
            or asset is None
            or asset.current_version_id != version.id
            or asset.state != "ready"
        ):
            raise MediaConflict("The approved public-film media is no longer current and ready.")
        renditions = database.scalars(
            select(MediaRendition).where(MediaRendition.version_id == version.id)
        ).all()
        captions = database.scalars(
            select(MediaCaptionTrack).where(MediaCaptionTrack.version_id == version.id)
        ).all()
        rendition_fields = (
            "id",
            "protocol",
            "content_type",
            "object_key",
            "width",
            "height",
            "bitrate_kbps",
        )
        caption_fields = ("id", "language", "kind", "content_type", "object_key", "is_default")

        def values(row: object, fields: tuple[str, ...]) -> tuple[Any, ...]:
            return tuple(getattr(row, field) for field in fields)

        if (
            {values(row, rendition_fields) for row in renditions}
            != {values(row, rendition_fields) for row in clip.processing_result.renditions}
            or {values(row, caption_fields) for row in captions}
            != {values(row, caption_fields) for row in clip.processing_result.captions}
            or any(row.tenant_id != self.pack.tenant_id for row in renditions)
            or any(row.tenant_id != self.pack.tenant_id for row in captions)
            or any(row.state != "ready" for row in captions)
        ):
            raise MediaConflict("The approved rendition/caption inventory changed.")

    def _bind(
        self,
        database: Session,
        actor: ActorContext,
        lease: PublicFilmImportAuthorization,
        *,
        replay: bool,
    ) -> tuple[ActivityMediaBindingResponse, ...]:
        results = []
        for index, clip in enumerate(self.pack.clips):
            key = f"public-film:{self.pack.manifest_sha256}:{index}"
            prior = database.scalar(
                select(ActivityMediaBinding.id).where(
                    ActivityMediaBinding.tenant_id == self.pack.tenant_id,
                    ActivityMediaBinding.approved_by_person_id == actor.person_id,
                    ActivityMediaBinding.idempotency_key == key,
                )
            )
            if (prior is not None) != replay:
                raise MediaConflict("The public-film binding history is occupied or incomplete.")
            result = self.service.bind_activity_media(
                database,
                actor,
                ActivityMediaBindingRequest(
                    activity_id=self.catalog.activity_ids[index],
                    module_id=self.catalog.module_id,
                    program_version_id=self.catalog.program_version_id,
                    program_id=self.catalog.program_id,
                    program_scope="tenant",
                    program_owner_key=self.pack.tenant_id,
                    asset_id=clip.asset_id,
                    version_id=clip.version_id,
                    approval_reference=f"PUBLIC-FILM-DEMO:{self.pack.manifest_sha256}",
                ),
                idempotency_key=key,
                public_film_authorization=lease,
            )
            if result.state != "approved":
                raise MediaConflict("The public-film binding approval is no longer active.")
            results.append(result)
        return tuple(results)


async def _run_cli(
    args: argparse.Namespace, token: str, settings: Any, pack: VerifiedPublicFilmPack
) -> PublicFilmImportResult:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(settings.database_url, pool_pre_ping=True, hide_parameters=True)
    try:
        async with (
            async_sessionmaker(engine, expire_on_commit=False)() as database,
            database.begin(),
        ):
            result = await PublicFilmImportApplication(
                database,
                token_pepper=settings.session_token_pepper.get_secret_value(),
                environment=settings.environment,
                release_id=settings.release_id,
                pack=pack,
            ).apply(
                session_token=token,
                command_id=args.command_id,
                expected_program_version_id=args.catalog_version_id,
                reason=args.reason,
            )
        # Exiting the transaction commits before any success can reach the CLI.
        return result
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    """Explicit deployment command; no root/URL overrides or token command-line arguments."""
    from ac_platform.application.asyncio_runtime import run_async
    from ac_platform.application.settings import Settings
    from ac_platform.authorization.cli import _Parser, _read_session_token
    from ac_platform.media import public_film_manifest

    try:
        parser = _Parser(description=__doc__, allow_abbrev=False)
        parser.add_argument(
            "--environment", required=True, choices=("test", "staging", "production")
        )
        parser.add_argument("--release-id", required=True)
        parser.add_argument("--tenant-id", type=UUID, required=True)
        parser.add_argument("--catalog-version-id", type=UUID, required=True)
        parser.add_argument("--manifest-sha256", required=True)
        parser.add_argument("--command-id", type=UUID, required=True)
        parser.add_argument("--reason", required=True, help="Non-secret immutable approval reason")
        parser.add_argument("--allow-production", action="store_true")
        parser.add_argument("--acknowledge-public-film-demonstration", action="store_true")
        args = parser.parse_args(argv)
        if (
            not args.acknowledge_public_film_demonstration
            or args.environment == "production"
            and not args.allow_production
            or os.getenv("AC_ENVIRONMENT", "").strip().lower() != args.environment
            or os.getenv("AC_RELEASE_ID") != args.release_id
            or not os.getenv("AC_DATABASE_URL", "").strip()
            or args.manifest_sha256 != public_film_manifest.MANIFEST_SHA256
        ):
            raise MediaForbidden("Explicit matching deployment and approval intent are required.")
        settings = Settings(
            _env_file=None, environment=args.environment, release_id=args.release_id
        )
        if (
            not settings.media_public_films_delivery_enabled
            or not settings.media_public_films_root
            or settings.public_learner_tenant_id != args.tenant_id
        ):
            raise MediaForbidden("The exact deployment public-film package must be configured.")
        pack = public_film_manifest.load_verified_public_film_pack(
            environment=settings.environment,
            release_id=settings.release_id,
            tenant_id=args.tenant_id,
            root=Path(settings.media_public_films_root),
            expected_manifest_sha256=args.manifest_sha256,
        )
        if args.catalog_version_id != public_film_catalog(pack).program_version_id:
            raise MediaForbidden("The package-owned catalog version must be acknowledged.")
        token = _read_session_token()
        result = run_async(_run_cli(args, token, settings, pack))
    except Exception:
        # Deliberately do not serialize database/provider/identity failures or input values.
        print("Public-film import refused; no successful import was reported.", file=sys.stderr)
        return 2
    print(json.dumps(asdict(result), default=str, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
