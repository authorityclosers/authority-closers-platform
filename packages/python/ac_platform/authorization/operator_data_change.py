"""Audited operator changes for an existing verified operations owner (AUT-828).

Approval references record authority; supplying them does not grant authority.
Dry run is the default. No session token is accepted or needed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from typing import Never
from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.application.release_identity import require_baked_release_id
from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.authorization.application import CapabilityApplication
from ac_platform.authorization.models import CapabilityGrant, CapabilityRevocation
from ac_platform.authorization.policy import CapabilityScope
from ac_platform.identity.models import Person, ProviderIdentity
from ac_platform.identity.services import normalize_email
from ac_platform.tenancy.models import Membership


class DataChangeRefused(ValueError):
    """Safe operator-facing refusal without input values or database details."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise DataChangeRefused("Invalid arguments; use --help.")


@dataclass(frozen=True)
class Command:
    action: str
    environment: str
    allow_production: bool
    email: str
    command_id: UUID
    approver: str
    issue: str
    reason: str
    apply: bool = False
    permission: str | None = None


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("add-operations-owner", "grant-platform-capability"):
        child = commands.add_parser(action, allow_abbrev=False)
        child.add_argument("--environment", required=True)
        child.add_argument("--allow-production", action="store_true")
        child.add_argument("--email", required=True)
        child.add_argument("--command-id", type=UUID, required=True)
        for name in ("approver", "issue", "reason"):
            child.add_argument(f"--{name}", required=True)
        child.add_argument("--apply", action="store_true")
        if action == "grant-platform-capability":
            child.add_argument("--permission", required=True)
    return parser


def _validate(settings: Settings, command: Command) -> UUID:
    if command.environment != settings.environment:
        raise DataChangeRefused("Environment must match the container settings.")
    if command.environment == "production" and not command.allow_production:
        raise DataChangeRefused("Production requires --allow-production.")
    if settings.operations_tenant_id is None:
        raise DataChangeRefused("An explicit operations tenant is required.")
    if command.action not in {"add-operations-owner", "grant-platform-capability"}:
        raise DataChangeRefused("Unknown command.")
    if command.action == "grant-platform-capability":
        if command.permission != "platform_release_manage":
            raise DataChangeRefused("Only platform_release_manage is allowed.")
    elif command.permission is not None:
        raise DataChangeRefused("Owner membership does not grant capabilities.")
    for reference in (command.approver, command.issue):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}", reference):
            raise DataChangeRefused("Use a non-secret approver and issue reference ID.")
    if not command.reason.strip() or len(command.reason) > 500:
        raise DataChangeRefused("A non-secret reason of 1–500 characters is required.")
    return settings.operations_tenant_id


def _payload(command: Command, person_id: UUID) -> dict[str, object]:
    return {
        "approver": command.approver,
        "issue": command.issue,
        "environment": command.environment,
        "command_id": str(command.command_id),
        "subject_person_id": str(person_id),
    }


def _check_audit(
    audit: AuditEvent | None,
    *,
    command: Command,
    tenant_id: UUID,
    action: str,
    resource_type: str,
    resource_id: str,
    payload: dict[str, object],
) -> None:
    if (
        audit is None
        or audit.tenant_id != tenant_id
        or audit.actor_type != "operator_data_change"
        or audit.actor_person_id is not None
        or audit.session_id is not None
        or audit.action != action
        or audit.resource_type != resource_type
        or audit.resource_id != resource_id
        or audit.payload != payload
        or audit.reason != command.reason.strip()
    ):
        raise DataChangeRefused("The command ID has different intent or attribution.")


async def execute_command(
    database: AsyncSession, settings: Settings, command: Command
) -> dict[str, object]:
    """Validate and change state inside one explicit caller-owned transaction."""
    tenant_id = _validate(settings, command)
    email = normalize_email(command.email).lower()
    app = CapabilityApplication(database, operations_tenant_id=tenant_id)
    # The existing fence serializes membership changes with bootstrap/grant/revoke.
    await app._governance()
    candidates = list(
        await database.scalars(select(Person.id).where(func.lower(Person.email) == email).limit(2))
    )
    if len(candidates) != 1:
        raise DataChangeRefused("Exactly one existing person must match the target email.")
    person = await app._person(candidates[0])
    if person.email is None or person.email.lower() != email:
        raise DataChangeRefused("The target email changed; inspect and retry.")
    provider = await database.scalar(
        select(ProviderIdentity.id)
        .where(ProviderIdentity.person_id == person.id)
        .with_for_update(read=True)
        .limit(1)
    )
    if provider is None:
        raise DataChangeRefused("The verified person must have a provider identity.")
    member = await database.scalar(
        select(Membership)
        .where(Membership.tenant_id == tenant_id, Membership.person_id == person.id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if member is not None and (
        member.role != "owner" or member.status != "active" or member.ended_at is not None
    ):
        raise DataChangeRefused("An existing membership must already be an active owner.")
    if command.action == "grant-platform-capability":
        if member is None:
            raise DataChangeRefused("An active operations owner membership is required.")
        return await _grant(app, command, person.id)
    return await _owner(app, command, person.id, member)


async def _owner(
    app: CapabilityApplication, command: Command, person_id: UUID, member: Membership | None
) -> dict[str, object]:
    db, tenant_id = app.database, app.operations_tenant_id
    payload = {**_payload(command, person_id), "tenant_id": str(tenant_id), "role": "owner"}
    prior = await db.get(AuditEvent, command.command_id)
    if (
        await db.get(CapabilityGrant, command.command_id) is not None
        or await db.get(CapabilityRevocation, command.command_id) is not None
    ):
        raise DataChangeRefused("The command ID has already been used for another change.")
    resource_id = f"{tenant_id}:{person_id}"
    if prior is not None:
        _check_audit(
            prior,
            command=command,
            tenant_id=tenant_id,
            action="tenancy.operations_owner_added",
            resource_type="membership",
            resource_id=resource_id,
            payload=payload,
        )
        if member is None:
            raise DataChangeRefused("The recorded owner membership is unavailable.")
    before = None if member is None else {"role": member.role, "status": member.status}
    after = {"role": "owner", "status": "active"}
    if command.apply and member is None:
        db.add(Membership(tenant_id=tenant_id, person_id=person_id, role="owner", status="active"))
        await db.flush()
        await AuditRepository(db).append(
            event_id=command.command_id,
            tenant_id=tenant_id,
            actor_type="operator_data_change",
            actor_person_id=None,
            action="tenancy.operations_owner_added",
            resource_type="membership",
            resource_id=resource_id,
            payload=payload,
            reason=command.reason.strip(),
        )
    return {
        "person_id_prefix": str(person_id)[:8],
        "tenant_id_prefix": str(tenant_id)[:8],
        "before": before,
        "after": after,
        "status": "applied" if command.apply else "dry_run",
        "no_op": member is not None,
        "capability_history_exists": bool(
            await db.scalar(select(exists().select_from(CapabilityGrant)))
        ),
    }


async def _grant(
    app: CapabilityApplication, command: Command, person_id: UUID
) -> dict[str, object]:
    db, tenant_id = app.database, app.operations_tenant_id
    permission = "platform_release_manage"
    manager_exists = await db.scalar(
        select(
            exists().where(
                CapabilityGrant.permission == "platform_access_manage",
                CapabilityGrant.scope_kind == "platform",
                ~exists().where(CapabilityRevocation.grant_id == CapabilityGrant.id),
            )
        )
    )
    if not manager_exists:
        raise DataChangeRefused("An unrevoked platform access manager must already exist.")
    payload = {
        **_payload(command, person_id),
        "permission": permission,
        "scope_kind": "platform",
        "tenant_id": None,
        "program_id": None,
    }
    prior = await db.get(CapabilityGrant, command.command_id)
    if await db.get(CapabilityRevocation, command.command_id) is not None:
        raise DataChangeRefused("The command ID has already been used for another change.")
    if prior is not None:
        if (
            prior.subject_person_id != person_id
            or prior.granted_by_person_id != person_id
            or prior.permission != permission
            or prior.scope_kind != "platform"
            or prior.tenant_id is not None
            or prior.program_id is not None
            or prior.reason != command.reason.strip()
        ):
            raise DataChangeRefused("The command ID has different grant intent.")
        _check_audit(
            await db.get(AuditEvent, prior.audit_event_id),
            command=command,
            tenant_id=tenant_id,
            action="authorization.capability_granted",
            resource_type="capability_grant",
            resource_id=str(command.command_id),
            payload=payload,
        )
    elif await db.get(AuditEvent, command.command_id) is not None:
        raise DataChangeRefused("The command ID has already been used for another change.")
    active = await app.active_grants(person_id)
    current = next(
        (row for row in active if row.permission == permission and row.scope_kind == "platform"),
        None,
    )
    no_op = prior is not None or current is not None
    grant_id = (
        prior.id if prior is not None else current.id if current is not None else command.command_id
    )
    before = sorted({row.permission for row in active if row.scope_kind == "platform"})
    after = before if no_op else sorted({*before, permission})
    if command.apply and not no_op:
        await app._insert_grant(
            person_id,
            None,
            command.command_id,
            person_id,
            permission,
            CapabilityScope("platform"),
            command.reason.strip(),
            actor_type="operator_data_change",
            audit_payload=_payload(command, person_id),
        )
    return {
        "grant_id": str(grant_id),
        "permission": permission,
        "status": "no_op" if no_op else "applied" if command.apply else "dry_run",
        "before": before,
        "after": after,
        "active_platform_permissions": after if command.apply else before,
    }


class _DryRunComplete(Exception):
    """Rollback the entire preview transaction even if a future helper writes."""


async def _run(settings: Settings, command: Command) -> dict[str, object]:
    _validate(settings, command)
    engine = create_async_engine(settings.database_url, pool_pre_ping=True, hide_parameters=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False, autoflush=False)() as db:
            try:
                async with db.begin():
                    result = await execute_command(db, settings, command)
                    if not command.apply:
                        raise _DryRunComplete
            except _DryRunComplete:
                pass
        return result
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    try:
        args = vars(_parser().parse_args(argv))
        args.setdefault("permission", None)
        command = Command(**args)
        settings = Settings(_env_file=None)
        _validate(settings, command)
        if command.environment in {"staging", "production"}:
            require_baked_release_id(settings.release_id)
        result = run_async(_run(settings, command))
    except (Exception, KeyboardInterrupt):
        # Settings, driver and argument failures can contain secrets or other emails.
        print(
            "data change refused or failed; retain the same command ID and intent for retry",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
