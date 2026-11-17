#!/usr/bin/env python3
"""The admin CLI's first primitives, on staging or production (owner-approved data changes).

Owner, 16-17 Nov 2026 (through the orchestrator): "every base-level primitive in CLI, MCP and
API". These are the first: changes an operator makes for an organisation from the back end,
each through the app's own service, nothing reimplemented.

    transfer-owner  --tenant-id T --person-id P   P becomes the owner; the owner becomes an
                    admin; both are e-mailed (OrganisationService.transfer_ownership). An
                    organisation has exactly one owner.
    set-role        --tenant-id T --person-id P --role admin|member
                    (OrganisationService.change_member_role); never the owner's role.
    rename-person   --tenant-id T --person-id P --name NAME
                    the account's display name, for a person who is an active member of T
                    (the app's own rename only lets a person rename themselves).
    reassign-leads  --tenant-id T --person-id FROM --to-person-id TO
                    every lead FROM owns in T goes to TO, an active member, through Lead
                    Desk's own bulk assign (each lead its own history line; at most 500).
    remove-member   --tenant-id T --person-id P
                    P's membership ends (OrganisationService.remove_member); the person and
                    the membership row stay. Never the owner.

Every command: dry run by default, in a read-only transaction, printing before and after;
``--apply`` needs a recorded database snapshot reference and commits once, with one audit event
(``admin.data_change_applied``) naming the approver, the issue, the operator and the run; the
same ``--command-id`` replays and changes nothing. Production also needs ``--allow-production``
and the container's own production settings. Prints ids, roles and display names only.

    docker exec -i ac-application-production-api-1 python - <command> --environment production \\
      --allow-production --tenant-id <workspace> --person-id <person> [--role|--name ...] \\
      --actor-person-id <operator person> --command-id <uuid> --approver <ref> \\
      --issue-reference <ref> --operator-reference <ref> --run-reference <uuid> \\
      [--apply --snapshot-reference <ref>] < scripts/data-changes/admin.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import NoReturn
from uuid import UUID, uuid5

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.application.release_identity import require_baked_release_id
from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import append_audit_event
from ac_platform.identity.models import Person
from ac_platform.kernel.errors import DomainError
from ac_platform.organisations.service import OrganisationCommandError, OrganisationService
from ac_platform.tenancy.models import Membership, Organisation, Tenant

ACTION = "admin.data_change_applied"
ENVIRONMENTS = ("staging", "production")
COMMANDS = ("transfer-owner", "set-role", "rename-person", "reassign-leads", "remove-member")
MAX_LEADS = 500
MAX_NAME = 200


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise OrganisationCommandError("invalid arguments; use --help")


class ResultDeliveryError(RuntimeError):
    """The transaction committed, but its JSON receipt could not be delivered."""


def _reference(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}", value):
        raise ValueError("a reference ID without credentials or personal data is required")
    return value


def _name(value: str) -> str:
    name = " ".join(value.split())
    if not 1 <= len(name) <= MAX_NAME or any(ord(c) < 0x20 or ord(c) == 0x7F for c in name):
        raise ValueError("a display name of 1 to 200 printable characters is required")
    return name


def _parser() -> argparse.ArgumentParser:
    parser = SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("--environment", choices=ENVIRONMENTS, required=True)
    parser.add_argument("--allow-production", action="store_true")
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--person-id", type=UUID, required=True)
    parser.add_argument("--role", choices=("admin", "member"))
    parser.add_argument("--name", type=_name)
    parser.add_argument("--to-person-id", type=UUID)
    parser.add_argument("--actor-person-id", type=UUID, required=True)
    parser.add_argument("--command-id", type=UUID, required=True)
    for name in ("approver", "issue-reference", "operator-reference"):
        parser.add_argument(f"--{name}", type=_reference, required=True)
    parser.add_argument("--run-reference", type=UUID, required=True)
    parser.add_argument("--snapshot-reference", type=_reference)
    parser.add_argument("--apply", action="store_true")
    return parser


def _check_command(args: argparse.Namespace) -> None:
    if (args.command == "set-role") != (args.role is not None):
        raise OrganisationCommandError("--role belongs to set-role only")
    if (args.command == "rename-person") != (args.name is not None):
        raise OrganisationCommandError("--name belongs to rename-person only")
    if (args.command == "reassign-leads") != (args.to_person_id is not None):
        raise OrganisationCommandError("--to-person-id belongs to reassign-leads only")
    if args.to_person_id is not None and args.to_person_id == args.person_id:
        raise OrganisationCommandError("the leads already belong to that person")


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
            "tool": "admin",
            "command": args.command,
            "environment": args.environment,
            "approver": args.approver,
            "issue": args.issue_reference,
            "operator": args.operator_reference,
            "run": str(args.run_reference),
        },
        sort_keys=True,
    )


def _intent(args: argparse.Namespace) -> dict[str, str]:
    intent = {
        "command": args.command,
        "tenant_id": str(args.tenant_id),
        "person_id": str(args.person_id),
        "actor_person_id": str(args.actor_person_id),
    }
    if args.role is not None:
        intent["role"] = args.role
    if args.name is not None:
        intent["name"] = args.name
    if args.to_person_id is not None:
        intent["to_person_id"] = str(args.to_person_id)
    return intent


async def _active_members(database: AsyncSession, tenant_id: UUID) -> list[Membership]:
    return list(
        await database.scalars(
            select(Membership).where(
                Membership.tenant_id == tenant_id,
                Membership.status == "active",
                Membership.ended_at.is_(None),
            )
        )
    )


async def _change(
    database: AsyncSession,
    service: OrganisationService,
    args: argparse.Namespace,
    child: UUID,
) -> dict[str, object]:
    members = {row.person_id: row for row in await _active_members(database, args.tenant_id)}
    owners = [row for row in members.values() if row.role == "owner"]
    if len(owners) != 1:
        raise OrganisationCommandError("exactly one active owner required")
    if args.command == "reassign-leads":
        return await _reassign(database, args, child, members)
    target = members.get(args.person_id)
    if args.command == "remove-member":
        if target is None:
            return {"status": "already_absent", "before": None, "after": None}
        current = {"role": target.role, "status": "active"}
        if target.role == "owner":
            raise OrganisationCommandError("the owner is never removed; transfer-owner first")
        if args.apply:
            await service.remove_member(
                args.tenant_id,
                args.person_id,
                child,
                actor_person_id=args.actor_person_id,
                operator_reference=args.operator_reference,
            )
        return {
            "status": "eligible",
            "before": current,
            "after": {"role": target.role, "status": "inactive"},
        }
    person = await database.get(Person, args.person_id)
    if person is None or person.status != "active" or target is None:
        raise OrganisationCommandError("the person must be an active member of the organisation")
    if args.command == "rename-person":
        before = {"name": person.display_name}
        after = {"name": args.name}
        if person.display_name == args.name:
            return {"status": "already_named", "before": before, "after": before}
        if args.apply:
            person.display_name = args.name
            person.revision += 1
            await database.flush()
        return {"status": "eligible", "before": before, "after": after}
    if args.command == "set-role":
        before = {"role": target.role}
        if target.role == "owner":
            raise OrganisationCommandError("the owner's role changes only by transfer-owner")
        if target.role == args.role:
            return {"status": f"already_{args.role}", "before": before, "after": before}
        if args.apply:
            await service.change_member_role(
                args.tenant_id,
                args.person_id,
                args.role,
                child,
                actor_person_id=args.actor_person_id,
                operator_reference=args.operator_reference,
            )
        return {"status": "eligible", "before": before, "after": {"role": args.role}}
    owner = owners[0]
    before = {"owner": str(owner.person_id), "person_role": target.role}
    if owner.person_id == args.person_id:
        return {"status": "already_owner", "before": before, "after": before}
    if person.email_verified_at is None:
        raise OrganisationCommandError("the new owner needs a verified e-mail")
    after = {"owner": str(args.person_id), "former_owner_role": "admin", "emails": "both"}
    if args.apply:
        await service.transfer_ownership(
            args.tenant_id,
            args.person_id,
            child,
            actor_person_id=args.actor_person_id,
            operator_reference=args.operator_reference,
        )
    return {"status": "eligible", "before": before, "after": after}


async def _reassign(
    database: AsyncSession,
    args: argparse.Namespace,
    child: UUID,
    members: dict[UUID, Membership],
) -> dict[str, object]:
    from datetime import UTC, datetime

    from ac_platform.lead_desk.contracts import BulkLeads
    from ac_platform.lead_desk.models import Lead
    from ac_platform.lead_desk.store import LeadDesk, Viewer

    receiver = members.get(args.to_person_id)
    if receiver is None:
        raise OrganisationCommandError("the leads go only to an active member")
    leads = list(
        await database.scalars(
            select(Lead.id)
            .where(Lead.tenant_id == args.tenant_id, Lead.owner_person_id == args.person_id)
            .order_by(Lead.id)
        )
    )
    before = {"leads_of_person": len(leads)}
    if not leads:
        return {"status": "no_leads", "before": before, "after": before}
    if len(leads) > MAX_LEADS:
        raise OrganisationCommandError("more than 500 leads; split the move")
    after = {"leads_of_person": 0, "moved_to": str(args.to_person_id), "moved": len(leads)}
    if args.apply:
        desk = LeadDesk(
            database,
            # The operator acts as a manager of the organisation, as onboarding does; each
            # lead's own history line names it.
            Viewer(
                person_id=args.actor_person_id,
                tenant_id=args.tenant_id,
                role="owner",
                name="AC operator",
            ),
            call_mode="phone",
            now=datetime.now(UTC),
        )
        done = await desk.bulk(
            BulkLeads(
                command_id=child,
                lead_ids=tuple(leads),
                action="assign",
                person_id=args.to_person_id,
            )
        )
        after["bulk"] = json.loads(done.model_dump_json())
    return {"status": "eligible", "before": before, "after": after}


async def _batch(
    database: AsyncSession, settings: Settings, args: argparse.Namespace
) -> dict[str, object]:
    _check_command(args)
    if settings.operations_tenant_id is None or settings.public_learner_tenant_id is None:
        raise OrganisationCommandError("protected tenant IDs must be configured")
    if args.apply and args.snapshot_reference is None:
        raise OrganisationCommandError("a recorded database snapshot is required before apply")
    if args.tenant_id in {settings.operations_tenant_id, settings.public_learner_tenant_id}:
        raise OrganisationCommandError("protected tenant refused")
    query = select(Organisation).where(Organisation.tenant_id == args.tenant_id)
    if args.apply:
        query = query.with_for_update()
    if await database.scalar(query) is None:
        raise OrganisationCommandError("registered organisation required")
    tenant = await database.get(Tenant, args.tenant_id)
    if tenant is None or tenant.status != "active":
        raise OrganisationCommandError("active tenant required")
    actor = await database.get(Person, args.actor_person_id)
    if actor is None or actor.status != "active" or actor.email_verified_at is None:
        raise OrganisationCommandError("named active verified operator person required")
    reason, intent = _reason(args), _intent(args)
    report: dict[str, object] = {
        "environment": args.environment,
        "release_id": settings.release_id,
        "tenant_id": str(args.tenant_id),
        "command": args.command,
        "mode": "apply" if args.apply else "dry_run",
        "attribution": json.loads(reason),
        "snapshot_reference": args.snapshot_reference,
        "command_id": str(args.command_id),
    }
    prior = await database.scalar(
        select(AuditEvent).where(AuditEvent.request_id == str(args.command_id)).limit(1)
    )
    if prior is not None:
        if (
            prior.tenant_id != args.tenant_id
            or prior.action != ACTION
            or prior.payload.get("intent") != intent
            or prior.reason != reason
        ):
            raise OrganisationCommandError("command ID has different intent or attribution")
        return {**report, "status": "replayed", "applied_result": prior.payload["result"]}
    service = OrganisationService(
        database,
        operations_tenant_id=settings.operations_tenant_id,
        public_learner_tenant_id=settings.public_learner_tenant_id,
    )
    child = uuid5(args.command_id, "canonical-app-command")
    result = await _change(database, service, args, child)
    if args.apply and result["status"] == "eligible":
        result["status"] = "applied"
        await append_audit_event(
            database,
            tenant_id=args.tenant_id,
            actor_person_id=args.actor_person_id,
            actor_type="operator",
            action=ACTION,
            resource_type={
                "rename-person": "person",
                "reassign-leads": "lead_owner",
            }.get(args.command, "organisation_membership"),
            resource_id=str(args.person_id),
            request_id=str(args.command_id),
            reason=reason,
            payload={
                "intent": intent,
                "result": result,
                "snapshot_reference": args.snapshot_reference,
                "canonical_command_id": str(child),
            },
        )
    return {**report, **result}


async def _run(args: argparse.Namespace) -> int:
    _check_command(args)
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
            "transaction completed but receipt delivery failed; read back the command ID",
            file=sys.stderr,
        )
        return 3
    except (ValueError, RuntimeError, OSError, SQLAlchemyError, DomainError):
        print("admin command refused or failed; nothing committed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
