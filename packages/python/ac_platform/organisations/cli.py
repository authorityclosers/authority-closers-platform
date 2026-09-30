"""Safe operator CLI for organisation creation and administration."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.application.release_identity import (
    ReleaseIdentityError,
    require_baked_release_id,
)
from ac_platform.application.settings import Settings
from ac_platform.identity.models import Person
from ac_platform.identity.services import normalize_email
from ac_platform.organisations.service import OrganisationCommandError, OrganisationService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("create", "add-member", "list-members", "set-domains"):
        child = commands.add_parser(action, allow_abbrev=False)
        child.add_argument("--environment", required=True)
        child.add_argument("--allow-production", action="store_true")
        if action == "create":
            child.add_argument("--name", required=True)
            child.add_argument("--owner-email", required=True)
        else:
            child.add_argument("--tenant-id", type=UUID, required=True)
        if action == "add-member":
            child.add_argument("--email", required=True)
            child.add_argument("--role", choices=("admin", "member"), required=True)
        if action == "set-domains":
            child.add_argument("--domain", action="append", default=[])
            child.add_argument("--auto-join", choices=("on", "off"), required=True)
        if action != "list-members":
            child.add_argument("--command-id", type=UUID, required=True)
            child.add_argument("--operator-reference", required=True)
            child.add_argument("--reason", required=True)
    return parser


def _environment(args: argparse.Namespace) -> tuple[str, Settings]:
    environment = args.environment.strip().lower()
    if environment not in {"local", "test", "development", "staging", "production"}:
        raise OrganisationCommandError("unsupported environment")
    configured = os.getenv("AC_ENVIRONMENT", "").strip().lower()
    if configured and configured != environment:
        raise OrganisationCommandError("--environment must match AC_ENVIRONMENT")
    if environment == "production" and not args.allow_production:
        raise OrganisationCommandError("production requires --allow-production")
    if not os.getenv("AC_DATABASE_URL", "").strip():
        raise OrganisationCommandError("an explicit AC_DATABASE_URL is required")
    settings = Settings(environment=environment)
    if settings.operations_tenant_id is None or settings.public_learner_tenant_id is None:
        raise OrganisationCommandError(
            "operations and public tenant IDs must be configured before organisation commands"
        )
    if environment in {"staging", "production"}:
        try:
            require_baked_release_id(settings.release_id)
        except ReleaseIdentityError as exc:
            raise OrganisationCommandError("a baked release identity is required") from exc
    return environment, settings


def _mask_email(email: str | None) -> str:
    if not email or "@" not in email:
        return "[redacted]"
    local, domain = email.rsplit("@", 1)
    return f"{local[:1]}***@{domain}"


def _json_value(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"unsupported output value: {type(value).__name__}")


async def _run(args: argparse.Namespace) -> int:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    _, settings = _environment(args)
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session, session.begin():
            service = OrganisationService(
                session,
                operations_tenant_id=cast(UUID, settings.operations_tenant_id),
                public_learner_tenant_id=cast(UUID, settings.public_learner_tenant_id),
            )
            if args.action == "create":
                email = normalize_email(args.owner_email, "owner email")
                person = await session.scalar(
                    select(Person).where(func.lower(Person.email) == email)
                )
                if person is None:
                    raise OrganisationCommandError("owner email does not identify a person")
                created = await service.create(
                    args.name,
                    person.id,
                    args.command_id,
                    args.operator_reference,
                    reason=args.reason,
                )
                output: Any = asdict(created)
            elif args.action == "add-member":
                email = normalize_email(args.email)
                person = await session.scalar(
                    select(Person).where(func.lower(Person.email) == email)
                )
                if person is None:
                    raise OrganisationCommandError("email does not identify a person")
                member = await service.add_member(
                    args.tenant_id,
                    person.id,
                    args.role,
                    args.command_id,
                    operator_reference=args.operator_reference,
                    reason=args.reason,
                )
                output = asdict(member)
                output["email"] = _mask_email(member.email)
            elif args.action == "list-members":
                members = await service.list_members(args.tenant_id)
                output = {
                    "members": [
                        {
                            "person_id": item.person_id,
                            "email": _mask_email(item.email),
                            "role": item.role,
                            "status": item.status,
                        }
                        for item in members
                    ]
                }
            else:
                domains = await service.set_domains_attested(
                    args.tenant_id,
                    args.domain,
                    args.auto_join == "on",
                    args.operator_reference,
                    args.command_id,
                    reason=args.reason,
                )
                output = {
                    "tenant_id": domains.tenant_id,
                    "version": domains.version,
                    "verified_domains": domains.verified_domains,
                    "auto_join": domains.auto_join,
                    "replayed": domains.replayed,
                }
        print(json.dumps(output, default=_json_value, sort_keys=True))
        return 0
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    try:
        return run_async(_run(_parser().parse_args(argv)))
    except (ValueError, SQLAlchemyError) as exc:
        message = (
            str(exc)
            if isinstance(exc, OrganisationCommandError)
            else "invalid command input"
            if isinstance(exc, ValueError)
            else "database command failed"
        )
        print(message, file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
