"""Inspect or persist analysis-settings revisions through the Admin service.

The CLI uses the same verified AC Admin identity and append-only receipt path as
the HTTP surface. It never edits production tables directly or changes accepted
plans.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Never
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.application.release_identity import require_baked_release_id
from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.analysis_settings import AnalysisSettings
from ac_platform.conversation_intelligence.analysis_settings_admin import (
    ConversationAnalysisSettingsAdmin,
)
from ac_platform.conversation_intelligence.application import ConversationApplication
from ac_platform.kernel.authz import ActorContext


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
    command.add_argument("--person-id", required=True, type=UUID)
    command.add_argument("--session-id", required=True, type=UUID)
    command.add_argument("--action", choices=("show", "history", "save"), default="save")
    command.add_argument("--limit", type=int, default=10)
    command.add_argument("--before-revision", type=int)
    command.add_argument("--expected-revision", type=int)
    command.add_argument("--idempotency-key")
    command.add_argument("--c4-max-requests", type=int)
    command.add_argument("--c4-max-completion-tokens", type=int)
    command.add_argument("--c5-max-completion-tokens", type=int)
    command.add_argument("--c5-output-profile", choices=("standard", "detailed"))
    return command


def validate_environment(args: argparse.Namespace) -> str:
    environment = str(args.environment).strip().lower()
    if environment not in {"local", "test", "development", "staging", "production"}:
        raise CommandError("Unsupported environment.")
    configured = os.getenv("AC_ENVIRONMENT", "").strip().lower()
    if configured and configured != environment:
        raise CommandError("The explicit environment must match AC_ENVIRONMENT.")
    if environment == "production" and args.action == "save" and not args.allow_production:
        raise CommandError("Production requires --allow-production.")
    if not os.getenv("AC_DATABASE_URL", "").strip():
        raise CommandError("An explicit AC_DATABASE_URL is required.")
    mutation_values = (
        args.expected_revision,
        args.idempotency_key,
        args.c4_max_requests,
        args.c4_max_completion_tokens,
        args.c5_max_completion_tokens,
        args.c5_output_profile,
    )
    if args.action == "save":
        if any(value is None for value in mutation_values):
            raise CommandError("Save requires a revision, idempotency key and all settings.")
        if not 1 <= len(args.idempotency_key) <= 128:
            raise CommandError("The idempotency key must be 1 to 128 characters.")
        if args.expected_revision < 0:
            raise CommandError("Use the current nonnegative revision.")
    elif any(value is not None for value in mutation_values):
        raise CommandError("Read actions do not accept save arguments.")
    if args.action != "history" and (args.limit != 10 or args.before_revision is not None):
        raise CommandError("History pagination requires --action history.")
    if not 1 <= args.limit <= 50 or (args.before_revision is not None and args.before_revision < 1):
        raise CommandError("Use a limit from 1 to 50 and a positive history revision.")
    return environment


async def save(args: argparse.Namespace) -> dict[str, object]:
    environment = validate_environment(args)
    settings = Settings(environment=environment)
    operations_tenant_id = settings.operations_tenant_id
    if operations_tenant_id is None or operations_tenant_id != args.tenant_id:
        raise CommandError("The tenant must match the configured AC operations workspace.")
    if environment in {"staging", "production"}:
        require_baked_release_id(settings.release_id)
    values = (
        AnalysisSettings(
            c4_max_requests=args.c4_max_requests,
            c4_max_completion_tokens=args.c4_max_completion_tokens,
            c5_max_completion_tokens=args.c5_max_completion_tokens,
            c5_output_profile=args.c5_output_profile,
        )
        if args.action == "save"
        else None
    )
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as database, database.begin():
            actor = ActorContext(
                person_id=args.person_id,
                session_id=args.session_id,
                tenant_id=args.tenant_id,
                permissions=frozenset({"admin_surface"}),
            )
            service = ConversationAnalysisSettingsAdmin(
                ConversationApplication(database),
                operations_tenant_id=operations_tenant_id,
            )
            if args.action == "show":
                result = await service.current(actor)
            elif args.action == "history":
                result = await service.history(
                    actor, limit=args.limit, before_revision=args.before_revision
                )
            else:
                assert values is not None
                result = await service.save(
                    actor,
                    values,
                    expected_revision=args.expected_revision,
                    key=args.idempotency_key,
                )
    finally:
        await engine.dispose()
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        result = run_async(save(parser().parse_args(argv)))
    except CommandError as exc:
        print(f"Analysis settings refused: {exc}", file=sys.stderr)
        return 2
    except Exception:
        # Database/authentication errors may include connection credentials or
        # private identity details; keep the CLI output operationally safe.
        print(
            "Analysis settings refused; check the Admin identity and database state.",
            file=sys.stderr,
        )
        return 2
    import json

    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
