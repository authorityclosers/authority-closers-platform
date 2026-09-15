"""Provision a non-login processing principal through an audited transaction."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Never
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.application.release_identity import require_baked_release_id
from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.guest_models import ConversationProcessingPrincipal
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership


class CommandError(ValueError):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise CommandError("Invalid arguments; use --help for the command contract.")


def parser() -> argparse.ArgumentParser:
    command = _Parser(description=__doc__, allow_abbrev=False)
    command.add_argument("--environment", required=True)
    command.add_argument("--allow-production", action="store_true")
    command.add_argument("--tenant-id", required=True, type=UUID)
    command.add_argument("--operator-reference", required=True)
    command.add_argument("--reason", required=True)
    return command


def validate_environment(args: argparse.Namespace) -> str:
    if not isinstance(args.environment, str):
        raise CommandError("An explicit environment is required.")
    environment = args.environment.strip().lower()
    if environment not in {"local", "test", "development", "staging", "production"}:
        raise CommandError("Unsupported environment.")
    configured = os.getenv("AC_ENVIRONMENT", "").strip().lower()
    if configured and configured != environment:
        raise CommandError("The explicit environment must match AC_ENVIRONMENT.")
    if environment == "production" and not args.allow_production:
        raise CommandError("Production requires --allow-production.")
    if not os.getenv("AC_DATABASE_URL", "").strip():
        raise CommandError("An explicit AC_DATABASE_URL is required.")
    return environment


async def provision(args: argparse.Namespace) -> dict[str, str]:
    environment = validate_environment(args)
    settings = Settings(environment=environment)
    if args.tenant_id != settings.public_learner_tenant_id:
        raise CommandError("The tenant must match the configured public learner workspace.")
    if environment in {"staging", "production"}:
        require_baked_release_id(settings.release_id)
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as database, database.begin():
            ownership = GuestOwnership(
                AcquisitionSessions(
                    database,
                    tenant_id=args.tenant_id,
                    policy_revision="processing-principal-v1",
                )
            )
            identifier = await ownership.provision(
                operator_reference=args.operator_reference, reason=args.reason
            )
            principal = await database.get(ConversationProcessingPrincipal, identifier)
            if principal is None:
                raise CommandError("The processing principal was not persisted.")
            result = {
                "environment": environment,
                "release_id": settings.release_id,
                "tenant_id": str(principal.tenant_id),
                "principal_id": str(principal.id),
                "processing_person_id": str(principal.person_id),
                "operator_reference": principal.operator_reference,
            }
    finally:
        await engine.dispose()
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        result = run_async(provision(parser().parse_args(argv)))
    except CommandError as exc:
        print(f"Processing setup refused: {exc}", file=sys.stderr)
        return 2
    except (ValueError, OSError, SQLAlchemyError):
        # Configuration/driver errors may contain connection credentials.
        print("Processing setup refused; check configuration and database state.", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
