"""Persist a reviewed analysis-settings revision through the Admin service.

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
    command.add_argument("--expected-revision", required=True, type=int)
    command.add_argument("--idempotency-key", required=True)
    command.add_argument("--c4-max-requests", required=True, type=int)
    command.add_argument("--c4-max-completion-tokens", required=True, type=int)
    command.add_argument("--c5-max-completion-tokens", required=True, type=int)
    command.add_argument("--c5-output-profile", required=True, choices=("standard", "detailed"))
    return command


def validate_environment(args: argparse.Namespace) -> str:
    environment = str(args.environment).strip().lower()
    if environment not in {"local", "test", "development", "staging", "production"}:
        raise CommandError("Unsupported environment.")
    configured = os.getenv("AC_ENVIRONMENT", "").strip().lower()
    if configured and configured != environment:
        raise CommandError("The explicit environment must match AC_ENVIRONMENT.")
    if environment == "production" and not args.allow_production:
        raise CommandError("Production requires --allow-production.")
    if not os.getenv("AC_DATABASE_URL", "").strip():
        raise CommandError("An explicit AC_DATABASE_URL is required.")
    if not isinstance(args.idempotency_key, str) or not 1 <= len(args.idempotency_key) <= 128:
        raise CommandError("The idempotency key must be 1 to 128 characters.")
    return environment


async def save(args: argparse.Namespace) -> dict[str, object]:
    environment = validate_environment(args)
    settings = Settings(environment=environment)
    operations_tenant_id = settings.operations_tenant_id
    if operations_tenant_id is None or operations_tenant_id != args.tenant_id:
        raise CommandError("The tenant must match the configured AC operations workspace.")
    if environment in {"staging", "production"}:
        require_baked_release_id(settings.release_id)
    values = AnalysisSettings(
        c4_max_requests=args.c4_max_requests,
        c4_max_completion_tokens=args.c4_max_completion_tokens,
        c5_max_completion_tokens=args.c5_max_completion_tokens,
        c5_output_profile=args.c5_output_profile,
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
            result = await ConversationAnalysisSettingsAdmin(
                ConversationApplication(database),
                operations_tenant_id=operations_tenant_id,
            ).save(
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
