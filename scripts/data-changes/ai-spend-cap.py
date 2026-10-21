#!/usr/bin/env python3
"""Set one AI spend cap in this environment, from the CLI (owner-approved data change).

Orchestrator, 21 Oct 2026: the owner approved "up to ₹300 to run Brain 4.0 on those calls
inside production (no copying out)" and does not want to click in Admin. This does what
Admin -> AI spend's one-click raise does (``ai_spend.admin_http``, POST
``/v1/admin/ai-spend/raise``), nothing reimplemented: the environment's settings get a new
revision through ``ai_spend.store.save`` (checked by ``ai_spend.policy``), audited as
``ai_spend.cap_raised`` (``ai_spend.cap_lowered`` when it goes down) with the old and new
settings and the reason, plus the approval (approver, issue, this script). Owner-approved
data change (AGENTS.md): dry run by default, before and after printed, one transaction,
idempotent (a cap already at the value changes nothing), audited with the approver and
the issue.

``--target`` is any cap the one-click raise moves: daily, monthly, backfill, or a feature
capped on the AI spend page (canary, pointer_review, partner_quote_facts, one_pass,
brain4_shadow). Daily and feature caps count the last 24 hours; monthly the month.

Who acts: the AC control account named by ``--control-email``, through its newest current
Admin session in the operations workspace, as an Admin request would. The script never
reads or prints a session token. No current session: refused (sign in to Admin once).

Run inside the deployed API container (its environment holds the database URL and the
operations tenant):

    docker exec -i ac-application-production-api-1 python - \\
      --environment production --allow-production \\
      --control-email <control account> --target brain4_shadow --cap-inr 300 \\
      --approver "Suyash Kulkarni (owner, relayed)" --issue <reference> \\
      --reason "<the owner's words>" [--apply] \\
      < scripts/data-changes/ai-spend-cap.py

On production: take a database snapshot before ``--apply``, show the owner the dry run.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

DATA_CHANGE = "scripts/data-changes/ai-spend-cap.py"
OPERATOR = "claude-laptop:ai-spend-cap"
RAISED = "ai_spend.cap_raised"
LOWERED = "ai_spend.cap_lowered"


class Refused(RuntimeError):
    """A stable, content-free reason the change was not made."""


class _DryRun(Exception):
    """Unwinds the transaction after a dry run."""


@dataclass(frozen=True)
class Command:
    environment: str
    control_email: str
    target: str
    cap_inr: int
    approver: str
    issue: str
    reason: str
    apply: bool = False


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-spend-cap", allow_abbrev=False)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--allow-production", action="store_true")
    parser.add_argument("--control-email", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--cap-inr", required=True, type=int)
    parser.add_argument("--approver", required=True)
    parser.add_argument("--issue", required=True)
    parser.add_argument("--reason", required=True, help="the approval, in the approver's words")
    parser.add_argument("--apply", action="store_true")
    return parser


def check(command: Command) -> Command:
    """The command, or why it can't run (before anything is read)."""
    from ac_platform.ai_spend import policy

    if command.target not in policy.RAISABLE:
        raise Refused("target_is_not_an_ai_spend_cap")
    ceiling = policy.MAX_MONTHLY_INR if command.target == "monthly" else policy.MAX_DAILY_INR
    if not 0 <= command.cap_inr <= ceiling:
        raise Refused("cap_out_of_range")
    reason = " ".join(command.reason.split())
    if not 1 <= len(reason) <= 200:
        raise Refused("reason_must_be_1_to_200_characters")
    approver, issue = command.approver.strip(), command.issue.strip()
    if not 1 <= len(approver) <= 120 or not 1 <= len(issue) <= 120:
        raise Refused("approver_and_issue_are_required")
    return Command(
        environment=command.environment,
        control_email=command.control_email,
        target=command.target,
        cap_inr=command.cap_inr,
        approver=approver,
        issue=issue,
        reason=reason,
        apply=command.apply,
    )


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
    from ac_platform.ai_spend import policy, store
    from ac_platform.audit.service import AuditRepository

    command = check(command)
    environment = policy.environment_name(command.environment)
    actor = await _actor(database, command, operations_tenant_id)
    before, revision = await store.read(database, environment)
    cap_before = policy.cap_of(before, command.target)
    result: dict[str, Any] = {
        "environment": environment,
        "target": command.target,
        "before": {"cap_inr": cap_before, "revision": revision},
        "after": {"cap_inr": command.cap_inr},
    }
    if cap_before == command.cap_inr:
        return {**result, "status": "no_op"}
    saved = await store.save(
        database,
        environment,
        policy.with_cap(before, command.target, command.cap_inr),
        person_id=actor.person_id,
        reason=command.reason,
        now=(clock or (lambda: datetime.now(UTC)))(),
    )
    after, _ = await store.read(database, environment)
    result["after"]["revision"] = saved
    if not command.apply:
        return {**result, "status": "dry_run"}
    await AuditRepository(database).append_for_actor(
        actor,
        action=RAISED if command.cap_inr > cap_before else LOWERED,
        resource_type="ai_spend_settings",
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
                target=args.target,
                cap_inr=args.cap_inr,
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
