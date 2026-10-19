#!/usr/bin/env python3
"""Grant platform_access_manage to an existing operations owner (owner order, 18 Oct 2026).

The owner (Suyash) ordered that admin@authorityclosers.com manages platform access, so
minute grants for a pilot organisation no longer depend on one other person's
account (AUT-2076). This mirrors ``operator_data_change grant-platform-capability``,
which only allows platform_release_manage, for the one permission it refuses:

- the target must be exactly one verified person with a provider identity and an
  active owner membership of the operations tenant (run ``add-operations-owner`` first);
- an unrevoked platform access manager must already exist (no bootstrap path here);
- one transaction under the capability governance fence; the grant and its audit
  event (actor_type ``operator_data_change``, approver and issue in the payload) are
  written together by ``CapabilityApplication._insert_grant``;
- dry run by default; idempotent by --command-id (a replay with the same intent is a
  no-op, different intent is refused); an existing active grant is a no-op.

Run inside the deployed API container (the baked package provides ac_platform):

    docker exec -i ac-application-production-api-1 python - \\
      --environment production --allow-production \\
      --email admin@authorityclosers.com --command-id <uuid> \\
      --approver suyash --issue AUT-2076 --reason "<non-secret reason>" [--apply] \\
      < scripts/data-changes/grant-platform-access-manage.py
"""

from __future__ import annotations

import argparse
import json
import sys
from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.application.release_identity import require_baked_release_id
from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.authorization.application import CapabilityApplication
from ac_platform.authorization.models import CapabilityGrant, CapabilityRevocation
from ac_platform.authorization.operator_data_change import (
    Command,
    DataChangeRefused,
    _check_audit,
    _payload,
    _validate,
)
from ac_platform.authorization.policy import CapabilityScope
from ac_platform.identity.models import Person, ProviderIdentity
from ac_platform.identity.services import normalize_email
from ac_platform.tenancy.models import Membership

PERMISSION = "platform_access_manage"
OPERATOR = "claude-laptop:platform-access-grant"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--allow-production", action="store_true")
    parser.add_argument("--email", required=True)
    parser.add_argument("--command-id", type=UUID, required=True)
    for name in ("approver", "issue", "reason"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--apply", action="store_true")
    return parser


async def execute(
    database: AsyncSession, settings: Settings, command: Command
) -> dict[str, object]:
    # _validate checks environment, production flag, reference IDs and reason; it only
    # allows platform_release_manage for its own action, so this script validates with
    # the owner-membership action and adds the one permission itself.
    tenant_id = _validate(settings, command)
    email = normalize_email(command.email).lower()
    app = CapabilityApplication(database, operations_tenant_id=tenant_id)
    await app._governance()
    candidates = list(
        await database.scalars(select(Person.id).where(func.lower(Person.email) == email).limit(2))
    )
    if len(candidates) != 1:
        raise DataChangeRefused("Exactly one existing person must match the target email.")
    person = await app._person(candidates[0])
    if person.email is None or person.email.lower() != email:
        raise DataChangeRefused("The target email changed; inspect and retry.")
    if (
        await database.scalar(
            select(ProviderIdentity.id)
            .where(ProviderIdentity.person_id == person.id)
            .with_for_update(read=True)
            .limit(1)
        )
        is None
    ):
        raise DataChangeRefused("The verified person must have a provider identity.")
    member = await database.scalar(
        select(Membership)
        .where(Membership.tenant_id == tenant_id, Membership.person_id == person.id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if member is None or member.role != "owner" or member.status != "active" or member.ended_at:
        raise DataChangeRefused("An active operations owner membership is required first.")
    manager_exists = await database.scalar(
        select(
            exists().where(
                CapabilityGrant.permission == PERMISSION,
                CapabilityGrant.scope_kind == "platform",
                ~exists().where(CapabilityRevocation.grant_id == CapabilityGrant.id),
            )
        )
    )
    if not manager_exists:
        raise DataChangeRefused("An unrevoked platform access manager must already exist.")
    audit_payload = {**_payload(command, person.id), "operator": OPERATOR}
    payload = {
        **audit_payload,
        "permission": PERMISSION,
        "scope_kind": "platform",
        "tenant_id": None,
        "program_id": None,
    }
    if await database.get(CapabilityRevocation, command.command_id) is not None:
        raise DataChangeRefused("The command ID has already been used for another change.")
    prior = await database.get(CapabilityGrant, command.command_id)
    if prior is not None:
        if (
            prior.subject_person_id != person.id
            or prior.granted_by_person_id != person.id
            or prior.permission != PERMISSION
            or prior.scope_kind != "platform"
            or prior.tenant_id is not None
            or prior.program_id is not None
            or prior.reason != command.reason.strip()
        ):
            raise DataChangeRefused("The command ID has different grant intent.")
        _check_audit(
            await database.get(AuditEvent, prior.audit_event_id),
            command=command,
            tenant_id=tenant_id,
            action="authorization.capability_granted",
            resource_type="capability_grant",
            resource_id=str(command.command_id),
            payload=payload,
        )
    elif await database.get(AuditEvent, command.command_id) is not None:
        raise DataChangeRefused("The command ID has already been used for another change.")
    active = await app.active_grants(person.id)
    current = next(
        (row for row in active if row.permission == PERMISSION and row.scope_kind == "platform"),
        None,
    )
    no_op = prior is not None or current is not None
    before = sorted({row.permission for row in active if row.scope_kind == "platform"})
    after = before if no_op else sorted({*before, PERMISSION})
    if command.apply and not no_op:
        await app._insert_grant(
            person.id,
            None,
            command.command_id,
            person.id,
            PERMISSION,
            CapabilityScope("platform"),
            command.reason.strip(),
            actor_type="operator_data_change",
            audit_payload=audit_payload,
        )
    return {
        "person_id_prefix": str(person.id)[:8],
        "permission": PERMISSION,
        "status": "no_op" if no_op else "applied" if command.apply else "dry_run",
        "before": before,
        "after": after,
    }


class _DryRun(Exception):
    pass


async def _run(settings: Settings, command: Command) -> dict[str, object]:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True, hide_parameters=True)
    result: dict[str, object] = {}
    try:
        async with async_sessionmaker(engine, expire_on_commit=False, autoflush=False)() as db:
            try:
                async with db.begin():
                    result = await execute(db, settings, command)
                    if not command.apply:
                        raise _DryRun
            except _DryRun:
                pass
        return result
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        command = Command(
            action="add-operations-owner",  # validation path that needs no permission
            environment=args.environment,
            allow_production=args.allow_production,
            email=args.email,
            command_id=args.command_id,
            approver=args.approver,
            issue=args.issue,
            reason=args.reason,
            apply=args.apply,
        )
        settings = Settings(_env_file=None)
        _validate(settings, command)
        if command.environment in {"staging", "production"}:
            require_baked_release_id(settings.release_id)
        result = run_async(_run(settings, command))
    except DataChangeRefused as refused:
        print(f"data change refused: {refused}", file=sys.stderr)
        return 2
    except (Exception, KeyboardInterrupt) as error:
        # Settings and driver failures can contain secrets; name the type only.
        print(f"data change failed: {type(error).__name__}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
