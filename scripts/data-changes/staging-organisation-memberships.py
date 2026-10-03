#!/usr/bin/env python3
"""Preview or apply explicitly approved staging organisation memberships (AUT-931).

Approval references record authority; supplying them does not grant authority.
No persons, tenants, owner changes, product switches or credits are created.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import NoReturn
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.application.release_identity import require_baked_release_id
from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.identity.models import Person
from ac_platform.identity.services import normalize_email
from ac_platform.organisations.service import OrganisationCommandError, OrganisationService
from ac_platform.tenancy.models import Membership, Organisation, Tenant


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # argparse's usual error can echo an email or an injected connection URL.
        raise OrganisationCommandError("invalid arguments; use --help")


def _reference(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}", value):
        raise ValueError("use a reference ID, without personal data or credentials")
    return value


def _target(value: str) -> UUID | str:
    return normalize_email(value).lower() if "@" in value else UUID(value)


def _parser() -> argparse.ArgumentParser:
    parser = SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--environment", choices=("staging",), required=True)
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument(
        "--target",
        type=_target,
        action="append",
        required=True,
        help="explicit email or person UUID; repeat for each approved target",
    )
    parser.add_argument("--role", choices=("admin", "member"), required=True)
    for name in ("approver", "issue-reference", "operator-reference"):
        parser.add_argument(f"--{name}", type=_reference, required=True)
    parser.add_argument("--run-reference", type=UUID, required=True)
    parser.add_argument(
        "--command-id",
        type=UUID,
        action="append",
        required=True,
        help="one stable UUID per --target, in the same order",
    )
    parser.add_argument("--apply", action="store_true")
    return parser


def _settings(args: argparse.Namespace) -> Settings:
    if args.environment != "staging" or os.getenv("AC_ENVIRONMENT") != "staging":
        raise OrganisationCommandError("this tool requires the staging runtime")
    if not os.getenv("AC_DATABASE_URL", "").strip():
        raise OrganisationCommandError("an injected database URL is required")
    settings = Settings(_env_file=None)
    if settings.environment != "staging":
        raise OrganisationCommandError("this tool requires the staging runtime")
    require_baked_release_id(settings.release_id)
    if settings.operations_tenant_id is None or settings.public_learner_tenant_id is None:
        raise OrganisationCommandError("protected tenant IDs must be configured")
    return settings


def _reason(args: argparse.Namespace) -> str:
    return json.dumps(
        {
            "tool": "AUT-931",
            "environment": "staging",
            "approver": args.approver,
            "issue": args.issue_reference,
            "operator": args.operator_reference,
            "run": str(args.run_reference),
        },
        sort_keys=True,
    )


def _membership(row: Membership | None) -> dict[str, str] | None:
    return None if row is None else {"role": row.role, "status": row.status}


def _mask(target: UUID | str) -> str:
    return (
        str(target) if isinstance(target, UUID) else f"{target[:1]}***@{target.rsplit('@', 1)[1]}"
    )


async def _batch(
    session: AsyncSession,
    settings: Settings,
    args: argparse.Namespace,
) -> dict[str, object]:
    """Caller owns the transaction; apply holds the service's registry fence."""
    if settings.operations_tenant_id is None or settings.public_learner_tenant_id is None:
        raise OrganisationCommandError("protected tenant IDs must be configured")
    if (
        not args.target
        or len(args.target) != len(args.command_id)
        or len(set(args.command_id)) != len(args.command_id)
        or len(set(args.target)) != len(args.target)
    ):
        raise OrganisationCommandError("provide unique targets and one unique command ID each")
    if args.tenant_id in {settings.operations_tenant_id, settings.public_learner_tenant_id}:
        raise OrganisationCommandError("protected tenant refused")
    registry_query = select(Organisation).where(Organisation.tenant_id == args.tenant_id)
    if args.apply:
        registry_query = registry_query.with_for_update()
    if await session.scalar(registry_query) is None:
        raise OrganisationCommandError("registered organisation required")
    tenant = await session.scalar(select(Tenant).where(Tenant.id == args.tenant_id))
    if tenant is None or tenant.status != "active":
        raise OrganisationCommandError("active tenant required")
    members = list(
        await session.scalars(select(Membership).where(Membership.tenant_id == args.tenant_id))
    )
    owners = [row for row in members if row.role == "owner" and row.status == "active"]
    if len(owners) != 1:
        raise OrganisationCommandError("exactly one active owner required")
    memberships = {row.person_id: row for row in members}
    reason = _reason(args)
    service = OrganisationService(
        session,
        operations_tenant_id=settings.operations_tenant_id,
        public_learner_tenant_id=settings.public_learner_tenant_id,
    )
    resolved: set[UUID] = set()
    results: list[dict[str, object]] = []
    for target, command_id in zip(args.target, args.command_id, strict=True):
        person_query = select(Person).where(
            Person.id == target if isinstance(target, UUID) else func.lower(Person.email) == target
        )
        if args.apply:
            person_query = person_query.with_for_update(read=True)
        people = list(await session.scalars(person_query))
        if len(people) > 1:
            raise OrganisationCommandError("target is ambiguous; use its approved person UUID")
        person = people[0] if people else None
        if person is not None:
            if person.id in resolved:
                raise OrganisationCommandError("targets resolve to the same person")
            resolved.add(person.id)
        member = memberships.get(person.id) if person else None
        if member is not None and member.role == "owner":
            raise OrganisationCommandError("owner target refused")
        prior = await session.scalar(
            select(AuditEvent).where(AuditEvent.request_id == str(command_id)).limit(1)
        )
        intent = {
            "person_id": str(person.id) if person else None,
            "role": args.role,
            "operator_reference": args.operator_reference,
        }
        if prior is not None and (
            prior.tenant_id != args.tenant_id
            or prior.action != "organisation.member_added"
            or prior.payload.get("intent") != intent
            or prior.reason != reason
        ):
            raise OrganisationCommandError("command ID has different intent or attribution")
        before = _membership(member)
        status = (
            "skipped_missing_person"
            if person is None
            else "skipped_inactive_person"
            if person.status != "active"
            else "skipped_unverified_person"
            if person.email is None or person.email_verified_at is None
            else "replayed"
            if prior is not None
            else "already_correct"
            if before == {"role": args.role, "status": "active"}
            else "eligible"
        )
        after = {"role": args.role, "status": "active"} if status == "eligible" else before
        if args.apply and status == "eligible":
            assert person is not None
            added = await service.add_member(
                args.tenant_id,
                person.id,
                args.role,
                command_id,
                operator_reference=args.operator_reference,
                reason=reason,
            )
            after = {"role": added.role, "status": added.status}
            status = "applied"
        results.append(
            {
                "target": _mask(target),
                "person_id": str(person.id) if person else None,
                "command_id": str(command_id),
                "status": status,
                "before": before,
                "after": after,
            }
        )
    return {
        "environment": "staging",
        "release_id": settings.release_id,
        "tenant_id": str(args.tenant_id),
        "mode": "apply" if args.apply else "dry_run",
        "desired_role": args.role,
        "owner_person_id": str(owners[0].person_id),
        "attribution": json.loads(reason),
        "targets": results,
    }


async def _run(args: argparse.Namespace) -> int:
    settings = _settings(args)
    engine = create_async_engine(
        settings.database_url, pool_pre_ping=True, echo=False, hide_parameters=True
    )
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with sessions() as session, session.begin():
            if not args.apply:
                # PostgreSQL enforces the preview's read-only guarantee.
                await session.execute(text("SET TRANSACTION READ ONLY"))
            output = await _batch(session, settings, args)
        # Emit success only after commit; failed batches have no partial report.
        print(json.dumps(output, sort_keys=True))
        return 0
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    try:
        return run_async(_run(_parser().parse_args(argv)))
    except (ValueError, RuntimeError, OSError, SQLAlchemyError):
        # Settings and DB exceptions may embed credentials or personal data.
        print("membership command refused or failed; no batch changes committed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
