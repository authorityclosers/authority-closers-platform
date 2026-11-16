#!/usr/bin/env python3
"""Add an organisation's sellers from the back end, on staging or production (owner-approved
membership data change).

Owner, 16 Nov 2026 (through the orchestrator): the Wise Life and iSolar sellers are "created
from the back end, each getting an invite e-mail, then signing in with Google and landing
inside the organisation". This is the app's own operator path, nothing reimplemented:

- an active person with a verified e-mail becomes a member at once
  (``OrganisationService.add_member``);
- anyone else gets an operator invite and the app's invitation e-mail
  (``OrganisationService.request_member(..., operator_auto_join=True)``); signing in with Google
  on that verified address joins them, no extra tap;
- a person already in the organisation keeps their role (``already_member``); an owner is never
  a target; a pending invite is not sent twice (``already_invited``).

Members only (the seller role). Roles beyond member and ownership stay with their own tools.
Dry run by default, in a read-only transaction; ``--apply`` commits the whole batch once, needs
a recorded database snapshot reference, and writes one audit event per target naming the
approver, the issue, the operator and the run. Production also needs ``--allow-production`` and
the container's own production settings. Rerunning the same command IDs replays, changes
nothing. Prints masked e-mails only.

    docker exec -i ac-application-production-api-1 python - --environment production \\
      --allow-production --tenant-id <workspace> --actor-person-id <operator person> \\
      --target seller@example.com --command-id <uuid> [...] --approver <ref> \\
      --issue-reference <ref> --operator-reference <ref> --run-reference <uuid> \\
      [--apply --snapshot-reference <ref>] < scripts/data-changes/organisation-members.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import NoReturn
from uuid import UUID, uuid5

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.application.release_identity import require_baked_release_id
from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import append_audit_event
from ac_platform.identity.models import Person
from ac_platform.identity.services import normalize_email
from ac_platform.kernel.errors import DomainError
from ac_platform.organisations.invitations import active_pending_invites
from ac_platform.organisations.service import OrganisationCommandError, OrganisationService
from ac_platform.tenancy.models import Membership, Organisation, Tenant

ACTION = "organisation.member_data_change_applied"
ENVIRONMENTS = ("staging", "production")
MAX_TARGETS = 50


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise OrganisationCommandError("invalid arguments; use --help")


class ResultDeliveryError(RuntimeError):
    """The transaction committed, but its JSON receipt could not be delivered."""


def _reference(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}", value):
        raise ValueError("a reference ID without credentials or personal data is required")
    return value


def _email(value: str) -> str:
    if "@" not in value:
        raise ValueError("an e-mail address is required")
    return normalize_email(value).lower()


def _parser() -> argparse.ArgumentParser:
    parser = SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--environment", choices=ENVIRONMENTS, required=True)
    parser.add_argument("--allow-production", action="store_true")
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--actor-person-id", type=UUID, required=True)
    parser.add_argument("--target", type=_email, action="append", required=True)
    parser.add_argument("--command-id", type=UUID, action="append", required=True)
    for name in ("approver", "issue-reference", "operator-reference"):
        parser.add_argument(f"--{name}", type=_reference, required=True)
    parser.add_argument("--run-reference", type=UUID, required=True)
    parser.add_argument("--snapshot-reference", type=_reference)
    parser.add_argument("--apply", action="store_true")
    return parser


def _settings(args: argparse.Namespace) -> Settings:
    if args.environment == "production" and not args.allow_production:
        raise OrganisationCommandError("production needs --allow-production")
    if os.getenv("AC_ENVIRONMENT") != args.environment:
        raise OrganisationCommandError("the runtime is not the named environment")
    if not os.getenv("AC_DATABASE_URL", "").strip():
        raise OrganisationCommandError("an injected database URL is required")
    settings = Settings(_env_file=None)
    if settings.environment != args.environment:
        raise OrganisationCommandError("the runtime is not the named environment")
    require_baked_release_id(settings.release_id)
    if settings.operations_tenant_id is None or settings.public_learner_tenant_id is None:
        raise OrganisationCommandError("protected tenant IDs must be configured")
    return settings


def _reason(args: argparse.Namespace) -> str:
    return json.dumps(
        {
            "tool": "organisation-members",
            "environment": args.environment,
            "approver": args.approver,
            "issue": args.issue_reference,
            "operator": args.operator_reference,
            "run": str(args.run_reference),
        },
        sort_keys=True,
    )


def _mask(email: str) -> str:
    return f"{email[:1]}***@{email.rsplit('@', 1)[1]}"


def _member(row: Membership | None) -> dict[str, object] | None:
    return (
        None
        if row is None
        else {"role": row.role, "status": row.status, "ended": row.ended_at is not None}
    )


async def _person(database: AsyncSession, email: str, *, lock: bool) -> Person | None:
    query = select(Person).where(func.lower(Person.email) == email)
    if lock:
        query = query.with_for_update(read=True, nowait=True)
    rows = list(await database.scalars(query))
    if len(rows) > 1:
        raise OrganisationCommandError("ambiguous person; resolve the account first")
    return rows[0] if rows else None


async def _add(
    database: AsyncSession,
    service: OrganisationService,
    args: argparse.Namespace,
    email: str,
    command_id: UUID,
    person: Person | None,
) -> dict[str, object]:
    membership = (
        await database.get(Membership, (args.tenant_id, person.id)) if person is not None else None
    )
    if membership is not None and membership.role == "owner":
        raise OrganisationCommandError("owner target refused")
    before = _member(membership)
    result: dict[str, object] = {
        "person_id": str(person.id) if person else None,
        "before": before,
        "after": before,
    }
    if person is not None and person.status != "active":
        return {**result, "status": "skipped_inactive_person"}
    if membership is not None and membership.status == "active" and membership.ended_at is None:
        return {**result, "status": "already_member"}
    if person is not None and person.email_verified_at is not None and person.email is not None:
        result.update(
            status="eligible", after={"role": "member", "status": "active", "ended": False}
        )
        if args.apply:
            await service.add_member(
                args.tenant_id,
                person.id,
                "member",
                command_id,
                actor_person_id=args.actor_person_id,
                operator_reference=args.operator_reference,
                reason=_reason(args),
            )
        return result
    pending = next(
        (
            row
            for row in await active_pending_invites(database, tenant_id=args.tenant_id)
            if row.email_normalized.lower() == email
        ),
        None,
    )
    if pending is not None:
        return {**result, "status": "already_invited", "invite_id": str(pending.id)}
    result.update(status="eligible_invite", after={"status": "invited", "role": "member"})
    if args.apply:
        invited = await service.request_member(
            args.tenant_id,
            email,
            "member",
            command_id,
            actor_person_id=args.actor_person_id,
            operator_reference=args.operator_reference,
            operator_auto_join=True,
        )
        result["invite_id"] = invited["invite_id"]
    return result


async def _batch(
    database: AsyncSession, settings: Settings, args: argparse.Namespace
) -> dict[str, object]:
    if settings.operations_tenant_id is None or settings.public_learner_tenant_id is None:
        raise OrganisationCommandError("protected tenant IDs must be configured")
    if args.apply and args.snapshot_reference is None:
        raise OrganisationCommandError("a recorded database snapshot is required before apply")
    if (
        not args.target
        or len(args.target) != len(args.command_id)
        or len(set(args.target)) != len(args.target)
        or len(set(args.command_id)) != len(args.command_id)
        or len(args.target) > MAX_TARGETS
    ):
        raise OrganisationCommandError("unique e-mail targets and command IDs (at most 50)")
    if args.tenant_id in {settings.operations_tenant_id, settings.public_learner_tenant_id}:
        raise OrganisationCommandError("protected tenant refused")
    query = select(Organisation).where(Organisation.tenant_id == args.tenant_id)
    if args.apply:
        query = query.with_for_update()
    if await database.scalar(query) is None:
        raise OrganisationCommandError("registered organisation required")
    tenant_query = select(Tenant).where(Tenant.id == args.tenant_id)
    if args.apply:
        tenant_query = tenant_query.with_for_update(read=True, nowait=True)
    tenant = await database.scalar(tenant_query)
    if tenant is None or tenant.status != "active":
        raise OrganisationCommandError("active tenant required")
    actor = await database.get(Person, args.actor_person_id)
    if actor is None or actor.status != "active" or actor.email_verified_at is None:
        raise OrganisationCommandError("named active verified operator person required")
    owners = list(
        await database.scalars(
            select(Membership).where(
                Membership.tenant_id == args.tenant_id,
                Membership.role == "owner",
                Membership.status == "active",
                Membership.ended_at.is_(None),
            )
        )
    )
    if len(owners) != 1:
        raise OrganisationCommandError("exactly one active owner required")
    service = OrganisationService(
        database,
        operations_tenant_id=settings.operations_tenant_id,
        public_learner_tenant_id=settings.public_learner_tenant_id,
    )
    reason = _reason(args)
    resolved: set[UUID] = set()
    rows: list[dict[str, object]] = []
    for email, command_id in zip(args.target, args.command_id, strict=True):
        intent = {"target": email, "role": "member", "actor_person_id": str(args.actor_person_id)}
        prior = await database.scalar(
            select(AuditEvent).where(AuditEvent.request_id == str(command_id)).limit(1)
        )
        if prior is not None:
            if (
                prior.tenant_id != args.tenant_id
                or prior.action != ACTION
                or prior.payload.get("intent") != intent
                or prior.reason != reason
            ):
                raise OrganisationCommandError("command ID has different intent or attribution")
            rows.append(
                {
                    "target": _mask(email),
                    "command_id": str(command_id),
                    "status": "replayed",
                    "applied_result": prior.payload["result"],
                }
            )
            continue
        person = await _person(database, email, lock=args.apply)
        if person is not None:
            if person.id in resolved:
                raise OrganisationCommandError("targets resolve to the same person")
            resolved.add(person.id)
        child = uuid5(command_id, "canonical-app-command")
        result = await _add(database, service, args, email, child, person)
        if args.apply and result["status"] in {"eligible", "eligible_invite"}:
            result["status"] = "applied"
            await append_audit_event(
                database,
                tenant_id=args.tenant_id,
                actor_person_id=args.actor_person_id,
                actor_type="operator",
                action=ACTION,
                resource_type="organisation_invite"
                if result.get("invite_id")
                else "organisation_membership",
                resource_id=result.get("person_id") or result.get("invite_id"),
                request_id=str(command_id),
                reason=reason,
                payload={
                    "intent": intent,
                    "result": result,
                    "snapshot_reference": args.snapshot_reference,
                    "canonical_command_id": str(child),
                },
            )
        rows.append({"target": _mask(email), "command_id": str(command_id), **result})
    return {
        "environment": args.environment,
        "release_id": settings.release_id,
        "tenant_id": str(args.tenant_id),
        "mode": "apply" if args.apply else "dry_run",
        "attribution": json.loads(reason),
        "snapshot_reference": args.snapshot_reference,
        "targets": rows,
    }


async def _run(args: argparse.Namespace) -> int:
    settings = _settings(args)
    engine = create_async_engine(
        settings.database_url, pool_pre_ping=True, echo=False, hide_parameters=True
    )
    committed = False
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with sessions() as database, database.begin():
            if not args.apply:
                await database.execute(text("SET TRANSACTION READ ONLY"))
            output = await _batch(database, settings, args)
        committed = True
        try:
            print(json.dumps(output, sort_keys=True), flush=True)
        except OSError as error:
            raise ResultDeliveryError from error
        return 0
    finally:
        try:
            await engine.dispose()
        except Exception as error:
            if committed:
                raise ResultDeliveryError from error
            raise


def main(argv: list[str] | None = None) -> int:
    try:
        return run_async(_run(_parser().parse_args(argv)))
    except ResultDeliveryError:
        print(
            "transaction completed but receipt delivery failed; read back the recorded command IDs",
            file=sys.stderr,
        )
        return 3
    except (ValueError, RuntimeError, OSError, SQLAlchemyError, DomainError):
        print(
            "organisation members command refused or failed; no batch changes committed",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
