"""grant-minutes: give one person analysis minutes in one audited step.

The owner, 13 Nov 2026: "Keep one simple way to give minutes straight away: a command
line, by user name / email id, so when someone's minutes run out we give them another
hour or two quickly."

    python -m ac_platform.conversation_intelligence.grant_minutes_cli \\
        --environment production --email someone@example.com --hours 2 \\
        --approver owner@example.com [--workspace <slug>] [--apply --allow-production]

A dry run by default: it prints who, which workspace, how much and what they have now,
and writes nothing. ``--apply`` writes the grant through the same audited path as
Admin's grant route (minute_grants.write_audited_grant): the learner ledger grant, an
audit event naming the approver, and the billing ledger lot. The approver must hold
platform access management. Someone in several workspaces needs ``--workspace``.
Output never carries a full email address, a price or a credential.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from typing import Never
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.application.settings import Settings
from ac_platform.authorization.application import CapabilityApplication
from ac_platform.conversation_intelligence.minute_account_admin import (
    EligibleLearnerBusy,
    EligibleLearnerUnavailable,
    InvalidMinuteAccountSnapshot,
    load_minute_account,
)
from ac_platform.conversation_intelligence.minute_grants import (
    GrantBeyondRange,
    write_audited_grant,
)
from ac_platform.conversation_intelligence.sales_xray_tenants import (
    LEARNER_ROLES,
    SALES_XRAY_MEMBER_ROLES,
    sales_xray_served_tenant_ids,
)
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Membership, Tenant

# An hour or two at a time (owner, 13 Nov 2026); a day's worth at most per run.
MAX_HOURS = 24
DEFAULT_REASON = "Owner-approved analysis minutes (grant-minutes command)"


class CommandError(ValueError):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise CommandError("Invalid arguments; use --help for the command contract.")


def parser() -> argparse.ArgumentParser:
    command = _Parser(description=__doc__, allow_abbrev=False)
    command.add_argument("--environment", required=True)
    command.add_argument("--email", required=True)
    command.add_argument("--hours", required=True, type=int)
    command.add_argument("--approver", required=True)
    command.add_argument("--workspace")
    command.add_argument("--reason", default=DEFAULT_REASON)
    command.add_argument("--apply", action="store_true")
    command.add_argument("--allow-production", action="store_true")
    return command


def masked(email: str) -> str:
    """ "ow***@example.com": enough to tell people apart, never the whole address."""

    local, _, domain = email.partition("@")
    return f"{local[:2]}***@{domain}" if domain else "***"


def validate(args: argparse.Namespace) -> str:
    environment = str(args.environment).strip().lower()
    if environment not in {"local", "test", "development", "staging", "production"}:
        raise CommandError("Unsupported environment.")
    configured = os.getenv("AC_ENVIRONMENT", "").strip().lower()
    if configured and configured != environment:
        raise CommandError("The explicit environment must match AC_ENVIRONMENT.")
    if environment == "production" and args.apply and not args.allow_production:
        raise CommandError("Writing in production requires --allow-production.")
    if not 1 <= args.hours <= MAX_HOURS:
        raise CommandError(f"Give 1 to {MAX_HOURS} hours at a time.")
    for value in (args.email, args.approver):
        if "@" not in value or len(value) > 320:
            raise CommandError("Use exact email addresses.")
    reason = " ".join(str(args.reason).split())
    if not 1 <= len(reason) <= 500:
        raise CommandError("The reason must be 1 to 500 characters.")
    args.reason = reason
    return environment


async def _person(database: AsyncSession, email: str) -> Person:
    people = (
        await database.scalars(
            select(Person).where(func.lower(Person.email) == email.strip().lower())
        )
    ).all()
    if len(people) != 1:
        raise CommandError(f"No single person has the email {masked(email)}.")
    return people[0]


async def grant(
    database: AsyncSession,
    *,
    settings: Settings,
    email: str,
    hours: int,
    approver_email: str,
    workspace: str | None,
    reason: str,
    apply: bool,
) -> dict[str, object]:
    """Plan (and with ``apply``, write) one grant inside the caller's transaction."""

    operations_tenant_id = settings.operations_tenant_id
    if operations_tenant_id is None:
        raise CommandError("The AC operations workspace isn't configured here.")
    person = await _person(database, email)
    approver = await _person(database, approver_email)
    capabilities = await CapabilityApplication(
        database, operations_tenant_id=operations_tenant_id
    ).active_grants(approver.id)
    if "platform_access_manage" not in {item.permission for item in capabilities}:
        raise CommandError("The approver doesn't hold platform access management.")

    served = await sales_xray_served_tenant_ids(settings, None, database)
    rows = (
        await database.execute(
            select(Tenant, Membership.role)
            .join(Membership, Membership.tenant_id == Tenant.id)
            .where(
                Membership.person_id == person.id,
                Membership.status == "active",
                Membership.ended_at.is_(None),
                Tenant.status == "active",
            )
            .order_by(Tenant.slug)
        )
    ).all()
    eligible = [
        (tenant, role, SALES_XRAY_MEMBER_ROLES if tenant.id in served else LEARNER_ROLES)
        for tenant, role in rows
        if role in (SALES_XRAY_MEMBER_ROLES if tenant.id in served else LEARNER_ROLES)
    ]
    if workspace is not None:
        wanted = workspace.strip().lower()
        eligible = [row for row in eligible if wanted in {row[0].slug.lower(), str(row[0].id)}]
    if len(eligible) != 1:
        choices = ", ".join(f"{tenant.slug} ({role})" for tenant, role, _ in eligible)
        raise CommandError(
            "Choose the workspace with --workspace: " + (choices or "none can take minutes")
        )
    tenant, role, roles = eligible[0]
    before = await load_minute_account(
        database, tenant_id=tenant.id, person_id=person.id, lock=apply
    )
    granted_before = sum(item.seconds for item in before.account.grants)
    plan: dict[str, object] = {
        "person": masked(person.email or ""),
        "workspace": tenant.slug,
        "role": role,
        "minutes": hours * 60,
        "approver": masked(approver.email or ""),
        "granted_minutes_before": granted_before // 60,
        "applied": False,
    }
    if not apply:
        return plan
    minutes = hours * 60
    key = f"grant-minutes:{uuid4()}"
    digest = hashlib.sha256(
        json.dumps(
            {
                "operation": "conversation_minute_grant",
                "tenant_id": str(tenant.id),
                "person_id": str(person.id),
                "minutes": minutes,
                "reason": reason,
                "idempotency_key": key,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    try:
        written = await write_audited_grant(
            database,
            tenant_id=tenant.id,
            person_id=person.id,
            minutes=minutes,
            reason=reason,
            approver_person_id=approver.id,
            session_id=None,
            request_id=None,
            idempotency_key=key,
            request_digest=digest,
            operations_tenant_id=operations_tenant_id,
            public_learner_tenant_id=settings.public_learner_tenant_id,
            roles=roles,
        )
    except EligibleLearnerUnavailable as error:
        raise CommandError("That person can't take minutes in this workspace.") from error
    except EligibleLearnerBusy as error:
        raise CommandError("That account is being updated; run the command again.") from error
    except InvalidMinuteAccountSnapshot as error:
        raise CommandError("That minute ledger can't be changed safely.") from error
    except GrantBeyondRange as error:
        raise CommandError("That grant is past the largest total the ledger keeps.") from error
    return {
        **plan,
        "applied": True,
        "grant_id": str(written.grant_id),
        "audit_event_id": str(written.audit_event_id),
        "granted_minutes_after": sum(item.seconds for item in written.state.account.grants) // 60,
    }


async def run(args: argparse.Namespace) -> dict[str, object]:
    environment = validate(args)
    settings = Settings(environment=environment)
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as database, database.begin():
            result = await grant(
                database,
                settings=settings,
                email=args.email,
                hours=args.hours,
                approver_email=args.approver,
                workspace=args.workspace,
                reason=args.reason,
                apply=args.apply,
            )
            if not args.apply:
                # A dry run writes nothing, not even a lock it took.
                await database.rollback()
    finally:
        await engine.dispose()
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        result = run_async(run(parser().parse_args(argv)))
    except CommandError as exc:
        print(f"grant-minutes refused: {exc}", file=sys.stderr)
        return 2
    except Exception:
        # Database errors may carry connection details or personal data: say only this.
        print("grant-minutes refused; check the emails and the database.", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    if not result.get("applied"):
        print("Dry run: nothing written. Add --apply to grant.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
