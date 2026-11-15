#!/usr/bin/env python3
"""Give one workspace a developer-platform tier or take that override away, and let connected
apps write or not (owner-approved data change).

Orchestrator, 14 Nov 2026: the 5,000-lead import proof runs in a fictional dev workspace, and
API keys come with the Organisation plan (a trial workspace may not make one). The owner gives
a workspace a tier with ``developer_platform.overrides`` in Admin -> Economics' settings
(``integrations.tiers.workspace_tier``: the override wins, billing on or off).

Orchestrator, 15 Nov 2026 (API gap 1, the owner's 14 Nov order: "pushing thousands of leads
using Claude"): ``developer_platform.advertise_writes`` lets connected apps (Claude, ChatGPT)
write. MCP then lists the write tools the plan allows, and Connect offers the plan's lead
writes to an app that asks for no scope (``oauth_http.connect_scopes``).

This sets ``--tenant`` with ``--tier`` or ``--remove``, ``--advertise-writes on|off``, or both,
through what Admin's "Save" does (PUT ``/v1/admin/economics/settings``,
``economics.admin_http``), nothing reimplemented: a new revision through
``economics.store.save`` (checked by ``economics.policy``), audited as
``economics.settings_saved`` with the old and new settings and the reason, plus the approval
(approver, issue, this script). Every other setting (fees, routes, the costs, the tiers' own
limits, other workspaces' overrides) stays as saved; if saving would change anything else, it
is refused. Owner-approved data change (AGENTS.md): dry run by default, before and after
printed, one transaction, idempotent (what is already saved changes nothing). ``--remove``
undoes an override, ``--advertise-writes off`` undoes writes.

The API reads the settings through a one-minute cache, so a change applies within a minute.

Who acts: the AC control account named by ``--control-email``, through its newest current
Admin session in the operations workspace, as an Admin request would. The script never reads
or prints a session token. No current session: refused (sign in to Admin once).

Run on ac with the dev-live API's settings (the slot the API runs from, a or b):

    sudo bash -c 'set -a; . /etc/authority-closers/development/api-live.env; set +a;
      cd /srv/authority-closers/development/live-backend/a && .venv/bin/python - \\
      --environment development --control-email <control account> \\
      [--tenant <workspace id> (--tier <tier> | --remove)] [--advertise-writes on|off] \\
      --approver "<approver>" --issue <reference> --reason "<their words>" [--apply]' \\
      < scripts/data-changes/developer-platform-override.py

In staging or production, inside the deployed API container:

    docker exec -i ac-application-production-api-1 python - \\
      --environment production --allow-production --control-email <control account> \\
      [--tenant <workspace id> (--tier <tier> | --remove)] [--advertise-writes on|off] \\
      --approver "<approver>" --issue <reference> --reason "<their words>" [--apply] \\
      < scripts/data-changes/developer-platform-override.py

On production: take a database snapshot before ``--apply``.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

DATA_CHANGE = "scripts/data-changes/developer-platform-override.py"
OPERATOR = "claude-laptop:developer-platform-override"
SAVED = "economics.settings_saved"
SECTION = "developer_platform"
# The tiers (integrations.tier_policy.TIERS); kept here so --help works without the package.
TIERS = ("unbilled", "trial", "personal", "organisation", "enterprise")
# The developer_platform fields this script may change; the rest of the section stays.
CHANGED = ("overrides", "advertise_writes")


class Refused(RuntimeError):
    """A stable, content-free reason the change was not made."""


class _DryRun(Exception):
    """Unwinds the transaction after a dry run."""


@dataclass(frozen=True)
class Command:
    environment: str
    control_email: str
    approver: str
    issue: str
    reason: str
    # With a workspace: its tier, or None to remove its override.
    tenant_id: UUID | None = None
    tier: str | None = None
    # None leaves it as saved.
    advertise_writes: bool | None = None
    apply: bool = False


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="developer-platform-override", allow_abbrev=False)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--allow-production", action="store_true")
    parser.add_argument("--control-email", required=True)
    parser.add_argument("--tenant", help="the workspace (tenant) id, with --tier or --remove")
    change = parser.add_mutually_exclusive_group()
    change.add_argument("--tier", choices=TIERS)
    change.add_argument("--remove", action="store_true", help="take the override away")
    parser.add_argument(
        "--advertise-writes", choices=("on", "off"), help="let connected apps write, or not"
    )
    parser.add_argument("--approver", required=True)
    parser.add_argument("--issue", required=True)
    parser.add_argument("--reason", required=True, help="the approval, in the approver's words")
    parser.add_argument("--apply", action="store_true")
    return parser


def tenant(raw: str) -> UUID:
    try:
        return UUID(raw.strip())
    except ValueError:
        raise Refused("tenant_must_be_a_workspace_id") from None


def command_from(args: argparse.Namespace) -> Command:
    """The command these arguments ask for, or why it can't be one."""
    if args.tenant is None and (args.tier is not None or args.remove):
        raise Refused("tier_and_remove_need_a_tenant")
    if args.tenant is not None and args.tier is None and not args.remove:
        raise Refused("a_tenant_needs_tier_or_remove")
    return Command(
        environment=args.environment,
        control_email=args.control_email,
        approver=args.approver,
        issue=args.issue,
        reason=args.reason,
        tenant_id=None if args.tenant is None else tenant(args.tenant),
        tier=None if args.remove else args.tier,
        advertise_writes=None if args.advertise_writes is None else args.advertise_writes == "on",
        apply=bool(args.apply),
    )


def check(command: Command) -> Command:
    """The command, or why it can't run (before anything is read)."""
    from ac_platform.integrations import tier_policy

    if command.tenant_id is None and command.advertise_writes is None:
        raise Refused("nothing_to_change")
    if command.tenant_id is None and command.tier is not None:
        raise Refused("tier_and_remove_need_a_tenant")
    if command.tier is not None and command.tier not in tier_policy.TIERS:
        raise Refused("tier_is_not_a_developer_platform_tier")
    reason = " ".join(command.reason.split())
    if not 1 <= len(reason) <= 200:
        raise Refused("reason_must_be_1_to_200_characters")
    approver, issue = command.approver.strip(), command.issue.strip()
    if not 1 <= len(approver) <= 120 or not 1 <= len(issue) <= 120:
        raise Refused("approver_and_issue_are_required")
    return Command(
        environment=command.environment,
        control_email=command.control_email,
        approver=approver,
        issue=issue,
        reason=reason,
        tenant_id=command.tenant_id,
        tier=command.tier,
        advertise_writes=command.advertise_writes,
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


def _state(section: dict[str, Any], key: str | None) -> dict[str, Any]:
    """What the printout shows of the section: the flag, the overrides' count, this one."""
    state: dict[str, Any] = {
        "advertise_writes": section["advertise_writes"],
        "overrides": len(section["overrides"]),
    }
    if key is not None:
        state["override"] = section["overrides"].get(key)
    return state


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
    from ac_platform.tenancy.models import Tenant

    command = check(command)
    now = (clock or (lambda: datetime.now(UTC)))()
    actor = await _actor(database, command, operations_tenant_id)
    key: str | None = None
    result: dict[str, Any] = {"environment": command.environment}
    if command.tenant_id is not None:
        workspace = await database.get(Tenant, command.tenant_id)
        if workspace is None:
            raise Refused("no_such_workspace")
        if workspace.status == "deleted":
            raise Refused("the_workspace_is_deleted")
        key = str(command.tenant_id)
        result["workspace"] = {"id": key, "name": workspace.name, "status": workspace.status}
    before, revision = await store.read(database)
    section = copy.deepcopy(before[SECTION])
    if key is not None:
        overrides = dict(section["overrides"])
        if command.tier is None:
            overrides.pop(key, None)
        else:
            overrides[key] = command.tier
        section["overrides"] = overrides
    if command.advertise_writes is not None:
        section["advertise_writes"] = command.advertise_writes
    try:
        wanted = policy.validate({**before, SECTION: section})
    except policy.SettingsError as error:
        raise Refused(f"settings_refused_{error.code}") from None

    # Only this workspace's override and the flag may change.
    def rest(config: dict[str, Any]) -> dict[str, Any]:
        others = {k: v for k, v in config[SECTION]["overrides"].items() if k != key}
        kept = {k: v for k, v in config[SECTION].items() if k not in CHANGED}
        return {**config, SECTION: {**kept, "other_overrides": others}}

    if rest(before) != rest(wanted):
        raise Refused("saving_would_change_other_settings")
    result["before"] = {"revision": revision, **_state(before[SECTION], key)}
    result["after"] = _state(wanted[SECTION], key)
    if all(before[SECTION][field] == wanted[SECTION][field] for field in CHANGED):
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
        command = check(command_from(args))
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
