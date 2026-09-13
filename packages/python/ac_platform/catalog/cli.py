"""Canonical operator commands for the one approved Free Course publication."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.application.release_identity import require_baked_release_id
from ac_platform.application.settings import Settings
from ac_platform.authorization.cli import _read_session_token
from ac_platform.catalog.free_course_media import FreeCourseMediaPromotionApplication
from ac_platform.catalog.free_course_publication import FreeCoursePublicationApplication
from ac_platform.http.auth import _with_role_permissions
from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.media.runtime import create_default_media_runtime
from ac_platform.media.service import MediaService


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
            if args.action in {"publish", "adopt-existing"}:
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
