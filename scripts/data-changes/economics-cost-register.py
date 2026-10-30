#!/usr/bin/env python3
"""Save Admin -> Economics' cost register in this environment, from the CLI (owner-approved data
change).

Owner, 30 Oct 2026: "yes please do this on your own" (enter AC's costs in the cost register on
dev, then production). This does what Admin -> Economics' "Save the cost register" does (PUT
``/v1/admin/economics/settings``, ``economics.admin_http``), nothing reimplemented: the
environment's economics settings get a new revision through ``economics.store.save`` (checked
by ``economics.policy``), audited as ``economics.settings_saved`` with the old and new settings
and the reason, plus the approval (approver, issue, this script). Only the register (``costs``)
and its rule (``cost_rules``) change; fees, routes, plan tiers and the rest stay as saved.
Owner-approved data change (AGENTS.md): dry run by default, before and after printed (the
number of costs and rupees a month by category; people are one total, never one line per
person), one transaction, idempotent (the same register changes nothing).

The register is ``{"costs": [...], "cost_rules": {...}}`` as JSON, base64 in ``--register-b64``,
from an operator input file kept on the ac host (/srv/authority-closers/operator-inputs/),
never in git: AC's own costs are not published.

Who acts: the AC control account named by ``--control-email``, through its newest current
Admin session in the operations workspace, as an Admin request would. The script never reads
or prints a session token. No current session: refused (sign in to Admin once).

Run inside the deployed API container (its environment holds the database URL and the
operations tenant):

    docker exec -i ac-application-production-api-1 python - \\
      --environment production --allow-production \\
      --control-email <control account> --register-b64 "$(base64 -w0 <register.json>)" \\
      --approver "Suyash Kulkarni (owner)" --issue <reference> \\
      --reason "<the owner's words>" [--apply] \\
      < scripts/data-changes/economics-cost-register.py

On production: take a database snapshot before ``--apply``.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import sys
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

DATA_CHANGE = "scripts/data-changes/economics-cost-register.py"
OPERATOR = "claude-laptop:economics-cost-register"
SAVED = "economics.settings_saved"
REGISTER_KEYS = ("costs", "cost_rules")


class Refused(RuntimeError):
    """A stable, content-free reason the change was not made."""


class _DryRun(Exception):
    """Unwinds the transaction after a dry run."""


@dataclass(frozen=True)
class Command:
    environment: str
    control_email: str
    register: dict[str, Any]
    approver: str
    issue: str
    reason: str
    apply: bool = False


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="economics-cost-register", allow_abbrev=False)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--allow-production", action="store_true")
    parser.add_argument("--control-email", required=True)
    parser.add_argument("--register-b64", required=True)
    parser.add_argument("--approver", required=True)
    parser.add_argument("--issue", required=True)
    parser.add_argument("--reason", required=True, help="the approval, in the approver's words")
    parser.add_argument("--apply", action="store_true")
    return parser


def decode(raw: str) -> dict[str, Any]:
    """The register from its base64 JSON, or why not (its content is never echoed)."""
    try:
        register = json.loads(base64.b64decode(raw, validate=True))
    except (binascii.Error, ValueError):
        raise Refused("register_is_not_base64_json") from None
    if (
        not isinstance(register, dict)
        or set(register) - set(REGISTER_KEYS)
        or "costs" not in register
    ):
        raise Refused("register_holds_costs_and_cost_rules_only")
    return register


def check(command: Command) -> Command:
    """The command, or why it can't run (before anything is read)."""
    from ac_platform.economics import policy

    try:
        policy.validate(command.register)
    except policy.SettingsError as error:
        raise Refused(f"register_refused_{error.code}") from None
    reason = " ".join(command.reason.split())
    if not 1 <= len(reason) <= 200:
        raise Refused("reason_must_be_1_to_200_characters")
    approver, issue = command.approver.strip(), command.issue.strip()
    if not 1 <= len(approver) <= 120 or not 1 <= len(issue) <= 120:
        raise Refused("approver_and_issue_are_required")
    return Command(
        environment=command.environment,
        control_email=command.control_email,
        register=command.register,
        approver=approver,
        issue=issue,
        reason=reason,
        apply=command.apply,
    )


def summary(config: dict[str, Any], month: date) -> dict[str, Any]:
    """What the register holds: how many costs, and rupees a month in total and by category."""
    from ac_platform.economics import costs

    by_category: dict[str, float] = {}
    for item in config["costs"]:
        by_category[item["category"]] = by_category.get(item["category"], 0.0) + costs.monthly(
            item, month
        )
    return {
        "costs": len(config["costs"]),
        "month_total": round(sum(by_category.values())),
        "by_category": {key: round(value) for key, value in sorted(by_category.items())},
        "platform_work": config["cost_rules"]["platform_work"],
    }


async def _actor(database: Any, command: Command, operations_tenant_id: UUID) -> Any:
    """The control account's newest current Admin session in the operations workspace."""
    from ac_platform.conversation_intelligence.provider_admin import CONTROL_ACCOUNTS
    from ac_platform.identity.models import Person
    from ac_platform.identity.models import Session as IdentitySession
    from ac_platform.kernel.authz import ActorContext

    email = command.control_email.strip().casefold()
    if email not in CONTROL_ACCOUNTS:
        raise Refused("control_email_is_not_a_provider_control_account")
    people = list(await database.scalars(select(Person).where(Person.email.ilike(email)).limit(2)))
    if len(people) != 1:
        raise Refused("exactly_one_person_must_match_the_control_email")
    now = datetime.now(UTC)
    session = await database.scalar(
        select(IdentitySession)
        .where(
            IdentitySession.person_id == people[0].id,
            IdentitySession.revoked_at.is_(None),
            IdentitySession.expires_at > now,
            IdentitySession.selected_tenant_id == operations_tenant_id,
        )
        .order_by(IdentitySession.created_at.desc())
        .limit(1)
    )
    if session is None:
        raise Refused("no_current_admin_session_sign_in_to_admin_once")
    return ActorContext(
        person_id=people[0].id,
        session_id=session.id,
        tenant_id=operations_tenant_id,
        permissions=frozenset({"admin_surface"}),
    )


async def execute(
    database: Any,
    command: Command,
    *,
    operations_tenant_id: UUID,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """One change in the caller's transaction (the caller commits only with --apply)."""
    from ac_platform.audit.service import AuditRepository
    from ac_platform.economics import policy, store

    command = check(command)
    now = (clock or (lambda: datetime.now(UTC)))()
    actor = await _actor(database, command, operations_tenant_id)
    before, revision = await store.read(database)
    wanted = policy.validate({**before, **command.register})
    result: dict[str, Any] = {
        "environment": command.environment,
        "before": {"revision": revision, **summary(before, now.date())},
        "after": summary(wanted, now.date()),
    }
    if all(before[key] == wanted[key] for key in REGISTER_KEYS):
        return {**result, "status": "no_op"}
    saved = await store.save(
        database, wanted, person_id=actor.person_id, reason=command.reason, now=now
    )
    after, _ = await store.read(database)
    result["after"]["revision"] = saved
    if not command.apply:
        return {**result, "status": "dry_run"}
    await AuditRepository(database).append_for_actor(
        actor,
        action=SAVED,
        resource_type="economics_settings",
        resource_id=str(saved),
        payload={
            "revision": saved,
            "old": before,
            "new": after,
            "reason": command.reason,
            "approval": {
                "approver": command.approver,
                "issue": command.issue,
                "data_change": DATA_CHANGE,
                "operator": OPERATOR,
            },
        },
    )
    return {**result, "status": "applied"}


async def _run(command: Command, settings: Any) -> dict[str, Any]:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(settings.database_url, pool_pre_ping=True, hide_parameters=True)
    result: dict[str, Any] = {}
    try:
        async with async_sessionmaker(engine, expire_on_commit=False, autoflush=False)() as db:
            try:
                async with db.begin():
                    result = await execute(
                        db, command, operations_tenant_id=settings.operations_tenant_id
                    )
                    if not command.apply or result["status"] != "applied":
                        raise _DryRun
            except _DryRun:
                pass
        return result
    finally:
        await engine.dispose()


def main(
    argv: list[str] | None = None,
    runner: Callable[..., Coroutine[Any, Any, dict[str, Any]]] | None = None,
) -> int:
    try:
        args = _parser().parse_args(argv)
        command = check(
            Command(
                environment=args.environment,
                control_email=args.control_email,
                register=decode(args.register_b64),
                approver=args.approver,
                issue=args.issue,
                reason=args.reason,
                apply=bool(args.apply),
            )
        )
        from ac_platform.application.asyncio_runtime import run_async
        from ac_platform.application.release_identity import require_baked_release_id
        from ac_platform.application.settings import Settings

        settings = Settings(_env_file=None)
        if command.environment != settings.environment:
            raise Refused("environment_must_match_the_container_settings")
        if command.environment == "production" and not args.allow_production:
            raise Refused("production_requires_allow_production")
        if settings.operations_tenant_id is None:
            raise Refused("an_explicit_operations_tenant_is_required")
        if command.environment in {"staging", "production"}:
            require_baked_release_id(settings.release_id)
        result = run_async((runner or _run)(command, settings))
    except Refused as refused:
        print(f"data change refused: {refused}", file=sys.stderr)
        return 2
    except (Exception, KeyboardInterrupt) as error:
        # Settings and driver failures can contain secrets; name the type only.
        print(f"data change failed: {type(error).__name__}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, default=str, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
