"""Package-native first-tenant owner bootstrap CLI."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict

from sqlalchemy.exc import SQLAlchemyError

from ac_platform.application.release_identity import (
    ReleaseIdentityError,
    require_baked_release_id,
)
from ac_platform.application.settings import Settings
from ac_platform.bootstrap.application import BootstrapApplication, BootstrapError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default=os.getenv("AC_BOOTSTRAP_EMAIL"))
    parser.add_argument("--tenant-slug", default=os.getenv("AC_BOOTSTRAP_TENANT_SLUG"))
    parser.add_argument("--tenant-name", default=os.getenv("AC_BOOTSTRAP_TENANT_NAME"))
    parser.add_argument("--environment", default=os.getenv("AC_ENVIRONMENT"))
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

    email = _required(args.email, "--email")
    tenant_slug = _required(args.tenant_slug, "--tenant-slug")
    tenant_name = _required(args.tenant_name, "--tenant-name")
    settings = Settings(environment=environment)
    if environment in {"staging", "production"}:
        require_baked_release_id(settings.release_id)

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session, session.begin():
            result = await BootstrapApplication(session).bootstrap_owner(
                email=email,
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
        return asyncio.run(_run(args))
    except (BootstrapError, OSError, ReleaseIdentityError, ValueError) as exc:
        print(f"bootstrap refused: {exc}", file=sys.stderr)
        return 2
    except SQLAlchemyError:
        print("bootstrap refused: database operation failed", file=sys.stderr)
        return 2


__all__ = ["main"]
