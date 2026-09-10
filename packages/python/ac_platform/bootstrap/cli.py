"""Package-native first-tenant owner bootstrap CLI."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.application.release_identity import (
    ReleaseIdentityError,
    require_baked_release_id,
)
from ac_platform.application.settings import Settings
from ac_platform.bootstrap.application import (
    BootstrapApplication,
    BootstrapError,
    BootstrapResult,
    OperationsTenantBootstrapResult,
    PublicLearnerTenantBootstrapResult,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default=os.getenv("AC_BOOTSTRAP_EMAIL"))
    parser.add_argument("--tenant-slug", default=os.getenv("AC_BOOTSTRAP_TENANT_SLUG"))
    parser.add_argument("--tenant-name", default=os.getenv("AC_BOOTSTRAP_TENANT_NAME"))
    parser.add_argument("--environment", default=os.getenv("AC_ENVIRONMENT"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--public-learner",
        action="store_true",
        help="bootstrap only the dedicated public learner tenant; creates no membership",
    )
    mode.add_argument(
        "--operations-only",
        action="store_true",
        help="bootstrap only the operations tenant and audit; creates no identity or membership",
    )
    parser.add_argument("--command-id", type=UUID, help="stable UUID for this operator intent")
    parser.add_argument(
        "--operator-reference", help="non-secret accountable operator/change reference"
    )
    parser.add_argument("--reason", help="non-secret reason for the operations-only bootstrap")
    parser.add_argument(
        "--allow-production",
        action="store_true",
        help="explicitly permit a production target; omitted targets are refused",
    )
    return parser


def _required(value: str | None, flag: str) -> str:
    normalized = (value or "").strip()
    if not normalized:
        raise BootstrapError(f"{flag} or its documented environment variable is required")
    return normalized


async def _run(args: argparse.Namespace) -> int:
    environment = _required(args.environment, "--environment").lower()
    configured_environment = os.getenv("AC_ENVIRONMENT", "").strip().lower()
    if configured_environment and configured_environment != environment:
        raise BootstrapError("--environment must match AC_ENVIRONMENT")
    if environment == "production" and not args.allow_production:
        raise BootstrapError("production requires the explicit --allow-production flag")
    if environment not in {"local", "test", "development", "staging", "production"}:
        raise BootstrapError("--environment is not supported")
    if not os.getenv("AC_DATABASE_URL", "").strip():
        raise BootstrapError("AC_DATABASE_URL is required; the local default is not allowed")

    tenant_slug = _required(args.tenant_slug, "--tenant-slug")
    tenant_name = _required(args.tenant_name, "--tenant-name")
    if args.operations_only:
        if args.email:
            raise BootstrapError("--operations-only does not accept an identity email")
        if args.command_id is None:
            raise BootstrapError("--command-id is required for --operations-only")
        operator_reference = _required(args.operator_reference, "--operator-reference")
        reason = _required(args.reason, "--reason")
    elif any(
        value is not None for value in (args.command_id, args.operator_reference, args.reason)
    ):
        raise BootstrapError("operator intent flags require --operations-only")
    settings = Settings(environment=environment)
    if environment in {"staging", "production"}:
        require_baked_release_id(settings.release_id)

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session, session.begin():
            application = BootstrapApplication(session)
            result: (
                BootstrapResult
                | PublicLearnerTenantBootstrapResult
                | OperationsTenantBootstrapResult
            )
            if args.operations_only:
                result = await application.bootstrap_operations_tenant(
                    command_id=args.command_id,
                    operator_reference=operator_reference,
                    reason=reason,
                    tenant_slug=tenant_slug,
                    tenant_name=tenant_name,
                    operations_tenant_id=settings.operations_tenant_id,
                )
            elif args.public_learner:
                result = await application.bootstrap_public_learner_tenant(
                    tenant_slug=tenant_slug,
                    tenant_name=tenant_name,
                    operations_tenant_id=settings.operations_tenant_id,
                )
            else:
                result = await application.bootstrap_owner(
                    email=_required(args.email, "--email"),
                    tenant_slug=tenant_slug,
                    tenant_name=tenant_name,
                )
    finally:
        await engine.dispose()
    print(json.dumps(asdict(result), default=str, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return run_async(_run(args))
    except (BootstrapError, OSError, ReleaseIdentityError, ValueError) as exc:
        print(f"bootstrap refused: {exc}", file=sys.stderr)
        return 2
    except SQLAlchemyError:
        print("bootstrap refused: database operation failed", file=sys.stderr)
        return 2


__all__ = ["main"]
