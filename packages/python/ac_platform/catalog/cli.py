"""Canonical operator commands for the one approved Free Course publication."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.application.release_identity import require_baked_release_id
from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.authorization.cli import _read_session_token
from ac_platform.catalog.free_course_media import FreeCourseMediaPromotionApplication
from ac_platform.catalog.free_course_publication import FreeCoursePublicationApplication
from ac_platform.catalog.models import ModulePrerequisite
from ac_platform.catalog.services import AsyncCatalogApplication
from ac_platform.http.auth import _with_role_permissions
from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.kernel.authz import ActorContext
from ac_platform.media.runtime import create_default_media_runtime
from ac_platform.media.service import MediaService

_SOURCE_PREREQUISITE_ACTION = "catalog.source_prerequisite_wired.v1"
_PREREQUISITE_NAMESPACE = UUID("9d8f7db4-0b5a-4a76-8be9-df73fb3f9ec3")


class FreeCourseCliError(Exception):
    """Operator input or the reviewed runtime composition was refused."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest="action", required=True)

    publish = commands.add_parser("publish", allow_abbrev=False)
    _common(publish)
    publish.add_argument("--source-program-id", type=UUID, required=True)
    publish.add_argument("--public-tenant-id", type=UUID, required=True)
    publish.add_argument("--command-id", type=UUID, required=True)
    publish.add_argument("--reason", required=True)
    publish.add_argument("--source-ref")
    publish.add_argument("--release-id")
    publish.add_argument("--reviewed-at")

    adopt = commands.add_parser("adopt-existing", allow_abbrev=False)
    _common(adopt)
    adopt.add_argument("--source-program-id", type=UUID, required=True)
    adopt.add_argument("--program-id", type=UUID, required=True)
    adopt.add_argument("--program-version-id", type=UUID, required=True)
    adopt.add_argument("--video-activity-id", type=UUID, required=True)
    adopt.add_argument("--public-tenant-id", type=UUID, required=True)
    adopt.add_argument("--command-id", type=UUID, required=True)
    adopt.add_argument("--reason", required=True)

    promote = commands.add_parser("promote-media", allow_abbrev=False)
    _common(promote)
    promote.add_argument("--publication-command-id", type=UUID, required=True)
    promote.add_argument("--command-id", type=UUID, required=True)
    promote.add_argument("--activity-id", type=UUID, required=True)
    promote.add_argument("--source-asset-id", type=UUID, required=True)
    promote.add_argument("--source-version-id", type=UUID, required=True)
    promote.add_argument("--media-owner-person-id", type=UUID, required=True)
    promote.add_argument("--public-tenant-id", type=UUID, required=True)
    promote.add_argument("--approval-reference", required=True)
    promote.add_argument("--supersedes-binding-id", type=UUID)

    prerequisite = commands.add_parser("wire-prerequisite", allow_abbrev=False)
    _common(prerequisite)
    prerequisite.add_argument("--program-id", type=UUID, required=True)
    prerequisite.add_argument("--program-version-id", type=UUID, required=True)
    prerequisite.add_argument("--module-id", type=UUID, required=True)
    prerequisite.add_argument("--prerequisite-module-id", type=UUID, required=True)
    prerequisite.add_argument("--command-id", type=UUID, required=True)
    prerequisite.add_argument("--reason", required=True)
    return parser


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--environment", required=True)
    parser.add_argument("--allow-production", action="store_true")


def _settings(args: argparse.Namespace) -> Settings:
    environment = str(args.environment).strip().lower()
    configured = os.getenv("AC_ENVIRONMENT", "").strip().lower()
    if environment not in {"local", "test", "development", "staging", "production"}:
        raise FreeCourseCliError("unsupported environment")
    if configured and configured != environment:
        raise FreeCourseCliError("--environment must match AC_ENVIRONMENT")
    if environment == "production" and not args.allow_production:
        raise FreeCourseCliError("production requires --allow-production")
    if not os.getenv("AC_DATABASE_URL", "").strip():
        raise FreeCourseCliError("an explicit AC_DATABASE_URL is required")
    settings = Settings(_env_file=None, environment=environment)
    if settings.operations_tenant_id is None:
        raise FreeCourseCliError("AC_OPERATIONS_TENANT_ID is required")
    if environment in {"staging", "production"}:
        require_baked_release_id(settings.release_id)
    return settings


def _reviewed_at(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError as error:
        raise FreeCourseCliError("--reviewed-at must be an ISO-8601 timestamp") from error


def _configured_studio_service(settings: Settings) -> MediaService:
    """Return the service from the validated deployment Studio graph."""

    runtime = create_default_media_runtime(settings)
    studio_runtime = runtime.studio_video_runtime
    if studio_runtime is None:
        raise FreeCourseCliError("the configured Studio filesystem runtime is unavailable")
    studio_runtime.validate()
    return studio_runtime.service


def _prerequisite_edge_id(
    *, program_version_id: UUID, module_id: UUID, prerequisite_module_id: UUID
) -> UUID:
    return uuid5(
        _PREREQUISITE_NAMESPACE,
        f"{program_version_id}:{module_id}:{prerequisite_module_id}",
    )


def _prerequisite_payload(
    *,
    program_id: UUID,
    program_version_id: UUID,
    module_id: UUID,
    prerequisite_module_id: UUID,
    prerequisite_id: UUID,
) -> dict[str, str]:
    return {
        "program_id": str(program_id),
        "program_version_id": str(program_version_id),
        "module_id": str(module_id),
        "prerequisite_module_id": str(prerequisite_module_id),
        "prerequisite_id": str(prerequisite_id),
        "status": "applied",
    }


async def _wire_prerequisite(
    database: Any,
    *,
    actor: ActorContext,
    tenant_id: UUID,
    program_id: UUID,
    program_version_id: UUID,
    module_id: UUID,
    prerequisite_module_id: UUID,
    command_id: UUID,
    reason: str,
) -> dict[str, str]:
    """Add one source-draft edge through the audited catalog boundary.

    Studio's HTTP authoring surface does not expose prerequisite edges. This
    command keeps the missing edge write in the existing catalog application,
    with fresh server-resolved actor authority, deterministic identity and an
    immutable audit receipt. It never accepts a caller-supplied actor or SQL
    payload.
    """

    if actor.tenant_id != tenant_id:
        raise FreeCourseCliError("the actor must select the operations tenant")
    if any(type(value) is not UUID or value.int == 0 for value in (
        program_id,
        program_version_id,
        module_id,
        prerequisite_module_id,
        command_id,
    )):
        raise FreeCourseCliError("all catalog IDs must be non-zero UUIDs")
    if (
        not isinstance(reason, str)
        or reason != reason.strip()
        or not reason
        or len(reason) > 500
        or any(ord(character) < 32 or ord(character) == 127 for character in reason)
    ):
        raise FreeCourseCliError("reason must be bounded text without control characters")

    prerequisite_id = _prerequisite_edge_id(
        program_version_id=program_version_id,
        module_id=module_id,
        prerequisite_module_id=prerequisite_module_id,
    )
    payload = _prerequisite_payload(
        program_id=program_id,
        program_version_id=program_version_id,
        module_id=module_id,
        prerequisite_module_id=prerequisite_module_id,
        prerequisite_id=prerequisite_id,
    )

    existing = await database.get(AuditEvent, command_id)
    if existing is not None:
        if (
            existing.tenant_id != tenant_id
            or existing.actor_person_id != actor.person_id
            or existing.action != _SOURCE_PREREQUISITE_ACTION
            or existing.resource_type != "module_prerequisite"
            or existing.resource_id != str(prerequisite_id)
            or existing.payload != payload
        ):
            raise FreeCourseCliError("the command ID has another audit meaning")
        edge = await database.get(ModulePrerequisite, prerequisite_id)
        if edge is None or (
            edge.program_id != program_id
            or edge.program_version_id != program_version_id
            or edge.module_id != module_id
            or edge.prerequisite_module_id != prerequisite_module_id
            or edge.tenant_id != tenant_id
        ):
            raise FreeCourseCliError("the prior prerequisite receipt has no matching edge")
        return {"command_id": str(command_id), **payload, "status": "replayed"}

    edge = await AsyncCatalogApplication(database).add_module_prerequisite(
        module_id,
        prerequisite_module_id,
        actor=actor,
        tenant_id=tenant_id,
        prerequisite_id=prerequisite_id,
    )
    if (
        edge.program_id != program_id
        or edge.program_version_id != program_version_id
        or edge.module_id != module_id
        or edge.prerequisite_module_id != prerequisite_module_id
        or edge.tenant_id != tenant_id
    ):
        raise FreeCourseCliError("the catalog returned an unexpected prerequisite edge")
    audit = await AuditRepository(database).append(
        event_id=command_id,
        tenant_id=tenant_id,
        actor_person_id=actor.person_id,
        session_id=actor.session_id,
        action=_SOURCE_PREREQUISITE_ACTION,
        resource_type="module_prerequisite",
        resource_id=prerequisite_id,
        payload=payload,
        reason=reason,
    )
    if audit.id != command_id:
        raise FreeCourseCliError("the prerequisite audit receipt was not committed")
    return {"status": "applied", "command_id": str(command_id), **payload}


async def _execute(args: argparse.Namespace) -> dict[str, Any]:
    settings = _settings(args)
    assert settings.operations_tenant_id is not None
    token = _read_session_token()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True, hide_parameters=True)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as database, database.begin():
            resolved = await AsyncIdentityApplication(
                database,
                token_pepper=settings.session_token_pepper.get_secret_value(),
            ).resolve_actor(token, require_tenant=True)
            # Keep the role-derived permission projection server-owned.  A
            # bare identity actor carries no client-authoritative permissions;
            # StudioAuthorization intersects this projection with current
            # membership and capability grants for every command.
            actor = _with_role_permissions(resolved).actor
            result: Any
            if args.action == "wire-prerequisite":
                result = await _wire_prerequisite(
                    database,
                    actor=actor,
                    tenant_id=settings.operations_tenant_id,
                    program_id=args.program_id,
                    program_version_id=args.program_version_id,
                    module_id=args.module_id,
                    prerequisite_module_id=args.prerequisite_module_id,
                    command_id=args.command_id,
                    reason=args.reason,
                )
            elif args.action in {"publish", "adopt-existing"}:
                publication = FreeCoursePublicationApplication(
                    database,
                    operations_tenant_id=settings.operations_tenant_id,
                    public_tenant_id=args.public_tenant_id,
                )
                if args.action == "adopt-existing":
                    result = await publication.adopt_existing(
                        actor=actor,
                        source_program_id=args.source_program_id,
                        program_id=args.program_id,
                        program_version_id=args.program_version_id,
                        video_activity_id=args.video_activity_id,
                        command_id=args.command_id,
                        reason=args.reason,
                    )
                else:
                    result = await publication.apply(
                        actor=actor,
                        source_program_id=args.source_program_id,
                        command_id=args.command_id,
                        reason=args.reason,
                        source_ref=args.source_ref,
                        release_id=args.release_id,
                        reviewed_at=_reviewed_at(args.reviewed_at),
                    )
            else:
                result = await FreeCourseMediaPromotionApplication(
                    database,
                    service=_configured_studio_service(settings),
                    operations_tenant_id=settings.operations_tenant_id,
                    public_tenant_id=args.public_tenant_id,
                ).apply(
                    actor=actor,
                    publication_command_id=args.publication_command_id,
                    command_id=args.command_id,
                    activity_id=args.activity_id,
                    source_asset_id=args.source_asset_id,
                    source_version_id=args.source_version_id,
                    media_owner_person_id=args.media_owner_person_id,
                    approval_reference=args.approval_reference,
                    supersedes_binding_id=args.supersedes_binding_id,
                )
            return asdict(result)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    try:
        result = run_async(_execute(_parser().parse_args(argv)))
    except (FreeCourseCliError, OSError, ValueError):
        # Settings/Pydantic and transport exceptions may contain raw input,
        # including a credential accidentally embedded in a URL.  Keep the
        # operator receipt bounded and independent of exception text.
        print(
            "free-course command refused: invalid or unavailable command input",
            file=sys.stderr,
        )
        return 2
    except Exception:
        print(
            "free-course command refused: command failed; retain the same intent for any retry",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, default=str, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
