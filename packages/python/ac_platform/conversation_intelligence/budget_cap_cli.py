"""Apply a pinned-release-approved shared budget cap through the Admin service.

The command uses the same verified AC Admin identity, transaction and audit
receipt path as the HTTP Admin surface. It never edits tables directly and
does not settle or release existing provider reservations.
"""

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
from ac_platform.conversation_intelligence.application import ConversationApplication
from ac_platform.conversation_intelligence.budget_admin import ConversationBudgetAdmin
from ac_platform.conversation_intelligence.hosted_runtime import load_pinned_approval
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
    command.add_argument("--new-cap-paise", required=True, type=int)
    command.add_argument("--reason", required=True)
    command.add_argument("--idempotency-key", required=True)
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
    if not settings.sales_xray_enabled:
        raise CommandError("Budget settings are not enabled in this release.")
    operations_tenant_id = settings.operations_tenant_id
    if operations_tenant_id is None or operations_tenant_id != args.tenant_id:
        raise CommandError("The tenant must match the configured AC operations workspace.")
    if environment in {"staging", "production"}:
        require_baked_release_id(settings.release_id)
    try:
        bundle = load_pinned_approval(settings)
    except ValueError:
        raise CommandError("The pinned budget approval is unavailable.") from None
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
            result = await ConversationBudgetAdmin(
                ConversationApplication(database),
                environment=environment,
                operations_tenant_id=operations_tenant_id,
            ).save(
                actor,
                bundle=bundle,
                new_cap_paise=args.new_cap_paise,
                expected_revision=args.expected_revision,
                reason=args.reason,
                key=args.idempotency_key,
            )
    finally:
        await engine.dispose()
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        result = run_async(save(parser().parse_args(argv)))
    except CommandError as exc:
        print(f"Budget settings refused: {exc}", file=sys.stderr)
        return 2
    except (ValueError, OSError, SQLAlchemyError):
        # Driver/configuration errors can contain database credentials.
        print(
            "Budget settings refused; check the Admin identity and database state.",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
