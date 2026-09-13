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
from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.media.runtime import create_default_media_runtime


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


async def _execute(args: argparse.Namespace) -> dict[str, Any]:
    settings = _settings(args)
    assert settings.operations_tenant_id is not None
    token = _read_session_token()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True, hide_parameters=True)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as database, database.begin():
            actor = (
                await AsyncIdentityApplication(
                    database,
                    token_pepper=settings.session_token_pepper.get_secret_value(),
                ).resolve_actor(token)
            ).actor
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
                runtime = create_default_media_runtime(settings)
                result = await FreeCourseMediaPromotionApplication(
                    database,
                    service=runtime.service,
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
    except (FreeCourseCliError, OSError, ValueError) as error:
        print(f"free-course command refused: {error}", file=sys.stderr)
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
