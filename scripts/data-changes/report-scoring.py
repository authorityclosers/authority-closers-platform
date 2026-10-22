#!/usr/bin/env python3
"""Choose a workspace's Report scoring from the CLI (owner-approved data change).

Orchestrator, 21 Oct 2026: turn Brain 4.0 beta on in Report settings for our own
company's workspace only. This does what Admin -> Report settings does, nothing
reimplemented: a version with the workspace's current settings and ``report.scoring``
changed (``ReportSettingsAdmin.create_version``; an identical earlier version is reused),
then that version chosen for the workspace alone (``ReportSettingsAdmin.choose``, scope
organisation). Both leave their own events and receipts; the run adds an audit event
``report_settings.scoring_chosen`` with the approval (approver, issue, this script).
Owner-approved data change (AGENTS.md): dry run by default, before and after printed, one
transaction, idempotent (a workspace already on that scoring changes nothing).

The workspace is our own company's (Admin's "company" kind: a registered organisation
verified for an email domain of the operations staff), never chosen by name. Exactly one
must exist unless ``--tenant-id`` names one of them.

``--every-workspace`` (owner, 22 Oct 2026: "the new brain live on production" for every
analysed call) chooses the same kind of version for everyone (Report settings' general
scope) instead, and lists each workspace's resulting scoring; a workspace with its own
organisation or industry choice keeps it and is listed under ``not_on_target``.

Who acts: the AC control account named by ``--control-email``, through its newest current
Admin session in the operations workspace, as an Admin request would. The script never
reads or prints a session token. No current session: refused (sign in to Admin once).

Run inside the deployed API container:

    docker exec -i ac-application-production-api-1 python - \\
      --environment production --allow-production \\
      --control-email <control account> --scoring brain4_beta \\
      --approver "Suyash Kulkarni (owner, relayed)" --issue <reference> \\
      --reason "<the approval, in the approver's words>" [--apply] \\
      < scripts/data-changes/report-scoring.py

On production: take a database snapshot before ``--apply``, show the owner the dry run.
``--scoring classic`` turns it back off the same way.
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

DATA_CHANGE = "scripts/data-changes/report-scoring.py"
OPERATOR = "claude-laptop:report-scoring"
CHOSEN = "report_settings.scoring_chosen"
SCORINGS = ("classic", "brain4_beta")
LABELS = {"classic": "Classic scoring", "brain4_beta": "Brain 4.0 AI coaching score"}


class Refused(RuntimeError):
    """A stable, content-free reason the change was not made."""


class _DryRun(Exception):
    """Unwinds the transaction after a dry run."""


@dataclass(frozen=True)
class Command:
    environment: str
    control_email: str
    scoring: str
    approver: str
    issue: str
    reason: str
    tenant_id: UUID | None = None
    every_workspace: bool = False
    apply: bool = False


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="report-scoring", allow_abbrev=False)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--allow-production", action="store_true")
    parser.add_argument("--control-email", required=True)
    parser.add_argument("--scoring", required=True)
    parser.add_argument("--tenant-id", type=UUID)
    parser.add_argument("--every-workspace", action="store_true")
    parser.add_argument("--approver", required=True)
    parser.add_argument("--issue", required=True)
    parser.add_argument("--reason", required=True, help="the approval, in the approver's words")
    parser.add_argument("--apply", action="store_true")
    return parser


def check(command: Command) -> Command:
    """The command, or why it can't run (before anything is read)."""
    if command.scoring not in SCORINGS:
        raise Refused("scoring_must_be_classic_or_brain4_beta")
    reason = " ".join(command.reason.split())
    if not 1 <= len(reason) <= 300:
        raise Refused("reason_must_be_1_to_300_characters")
    approver, issue = command.approver.strip(), command.issue.strip()
    if not 1 <= len(approver) <= 120 or not 1 <= len(issue) <= 60:
        raise Refused("approver_and_issue_are_required")
    if command.every_workspace and command.tenant_id is not None:
        raise Refused("every_workspace_takes_no_tenant_id")
    return Command(
        environment=command.environment,
        control_email=command.control_email,
        scoring=command.scoring,
        approver=approver,
        issue=issue,
        reason=reason,
        tenant_id=command.tenant_id,
        every_workspace=command.every_workspace,
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


async def _company(
    database: Any, command: Command, operations_tenant_id: UUID, personal_tenant_id: UUID | None
) -> Any:
    from ac_platform.organisations.workspace_kinds import classify_workspaces

    workspaces = await classify_workspaces(
        database,
        operations_tenant_id=operations_tenant_id,
        personal_tenant_id=personal_tenant_id,
    )
    company = [w for w in workspaces.values() if w.kind == "company" and w.status == "active"]
    if command.tenant_id is not None:
        company = [w for w in company if w.tenant_id == command.tenant_id]
        if not company:
            raise Refused("tenant_is_not_our_own_company_workspace")
    if len(company) != 1:
        raise Refused("exactly_one_company_workspace_is_required_name_it_with_tenant_id")
    return company[0]


async def execute(
    database: Any,
    command: Command,
    *,
    operations_tenant_id: UUID,
    personal_tenant_id: UUID | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """One change in the caller's transaction (the caller commits only with --apply)."""
    from ac_platform.audit.service import AuditRepository
    from ac_platform.conversation_intelligence.application import ConversationApplication
    from ac_platform.conversation_intelligence.report_settings_admin import (
        ChoiceIntent,
        ReportSettingsAdmin,
        VersionIntent,
    )

    command = check(command)
    actor = await _actor(database, command, operations_tenant_id)
    if command.every_workspace:
        return await _everyone(
            database,
            command,
            actor,
            operations_tenant_id=operations_tenant_id,
            personal_tenant_id=personal_tenant_id,
            now=clock or (lambda: datetime.now(UTC)),
        )
    workspace = await _company(database, command, operations_tenant_id, personal_tenant_id)
    tenant = workspace.tenant_id
    now = clock or (lambda: datetime.now(UTC))
    admin = ReportSettingsAdmin(
        ConversationApplication(database, clock=now),
        operations_tenant_id=operations_tenant_id,
        organisation_ids=(tenant,),
        personal_tenant_id=personal_tenant_id,
    )
    await admin.admit(actor)
    before = await admin.store.effective(tenant)
    scoring_before = before["settings"]["report"]["scoring"]
    result: dict[str, Any] = {
        "workspace": {"tenant_id": str(tenant), "name": workspace.name, "kind": workspace.kind},
        "before": {
            "version": before["version"]["number"],
            "source": before["source"],
            "scoring": scoring_before,
        },
    }
    if scoring_before == command.scoring:
        return {**result, "after": result["before"], "status": "no_op"}
    versions = await admin.store.versions()
    _, base = versions[before["version"]["number"]]
    wanted = base.model_copy(
        update={"report": base.report.model_copy(update={"scoring": command.scoring})}
    )
    number = next(
        (
            n
            for n, (_, settings) in sorted(versions.items())
            if settings.digest() == wanted.digest()
        ),
        None,
    )
    created = number is None
    key = f"data-change:report-scoring:{command.issue}:{tenant}:{command.scoring}"
    if number is None:
        version = await admin.create_version(
            actor,
            VersionIntent(
                label=LABELS[command.scoring],
                note=command.reason[:500],
                base_number=before["version"]["number"],
                settings=wanted,
            ),
            key=f"{key}:version"[:128],
        )
        number = int(version["number"])
    current = await admin.store.latest("organisation", tenant_id=tenant)
    await admin.choose(
        actor,
        ChoiceIntent(
            scope="organisation",
            tenant_id=tenant,
            version_number=number,
            expected_version_number=None if current is None else current.version_number,
            reason=command.reason[:300],
        ),
        key=f"{key}:choice"[:128],
    )
    after = await admin.store.effective(tenant)
    result["after"] = {
        "version": after["version"]["number"],
        "source": after["source"],
        "scoring": after["settings"]["report"]["scoring"],
        "version_created": created,
    }
    if not command.apply:
        return {**result, "status": "dry_run"}
    await AuditRepository(database).append_for_actor(
        actor,
        action=CHOSEN,
        resource_type="conversation_report_settings_version",
        resource_id=str(number),
        payload={
            "tenant_id": str(tenant),
            "before": result["before"],
            "after": result["after"],
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


async def _everyone(
    database: Any,
    command: Command,
    actor: Any,
    *,
    operations_tenant_id: UUID,
    personal_tenant_id: UUID | None,
    now: Callable[[], datetime],
) -> dict[str, Any]:
    """The general scope: one version for every workspace without its own choice."""
    from ac_platform.audit.service import AuditRepository
    from ac_platform.conversation_intelligence.application import ConversationApplication
    from ac_platform.conversation_intelligence.report_settings_admin import (
        ChoiceIntent,
        ReportSettingsAdmin,
        VersionIntent,
    )
    from ac_platform.organisations.workspace_kinds import classify_workspaces, ordered

    kinds = await classify_workspaces(
        database,
        operations_tenant_id=operations_tenant_id,
        personal_tenant_id=personal_tenant_id,
    )
    served = [
        w
        for w in ordered(kinds.values())
        if w.kind in ("company", "customer", "personal") and w.status == "active"
    ]
    admin = ReportSettingsAdmin(
        ConversationApplication(database, clock=now),
        operations_tenant_id=operations_tenant_id,
        organisation_ids=tuple(w.tenant_id for w in served),
        personal_tenant_id=personal_tenant_id,
    )
    await admin.admit(actor)

    async def states() -> list[dict[str, Any]]:
        rows = []
        for w in served:
            effective = await admin.store.effective(w.tenant_id)
            rows.append(
                {
                    "tenant_id": str(w.tenant_id),
                    "name": w.name,
                    "kind": w.kind,
                    "version": effective["version"]["number"],
                    "source": effective["source"],
                    "scoring": effective["settings"]["report"]["scoring"],
                }
            )
        return rows

    versions = await admin.store.versions()
    general = await admin.store.latest("general")
    current = None if general is None else general.version_number
    base_number = current if current in versions else 1
    _, base = versions[base_number]
    result: dict[str, Any] = {
        "scope": "general",
        "before": {"version": current, "scoring": base.report.scoring},
    }
    if base.report.scoring == command.scoring:
        rows = await states()
        return {
            **result,
            "after": result["before"],
            "workspaces": rows,
            "not_on_target": [r for r in rows if r["scoring"] != command.scoring],
            "status": "no_op",
        }
    wanted = base.model_copy(
        update={"report": base.report.model_copy(update={"scoring": command.scoring})}
    )
    number = next(
        (
            n
            for n, (_, settings) in sorted(versions.items())
            if settings.digest() == wanted.digest()
        ),
        None,
    )
    created = number is None
    key = f"data-change:report-scoring:{command.issue}:general:{command.scoring}"
    if number is None:
        version = await admin.create_version(
            actor,
            VersionIntent(
                label=LABELS[command.scoring],
                note=command.reason[:500],
                base_number=base_number,
                settings=wanted,
            ),
            key=f"{key}:version"[:128],
        )
        number = int(version["number"])
    await admin.choose(
        actor,
        ChoiceIntent(
            scope="general",
            version_number=number,
            expected_version_number=current,
            reason=command.reason[:300],
        ),
        key=f"{key}:choice"[:128],
    )
    rows = await states()
    missed = [r for r in rows if r["scoring"] != command.scoring]
    result["after"] = {"version": number, "scoring": command.scoring, "version_created": created}
    result["workspaces"] = rows
    result["not_on_target"] = missed
    if not command.apply:
        return {**result, "status": "dry_run"}
    await AuditRepository(database).append_for_actor(
        actor,
        action=CHOSEN,
        resource_type="conversation_report_settings_version",
        resource_id=str(number),
        payload={
            "scope": "general",
            "before": result["before"],
            "after": result["after"],
            "workspaces": len(rows),
            "not_on_target": [r["tenant_id"] for r in missed],
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
                        db,
                        command,
                        operations_tenant_id=settings.operations_tenant_id,
                        personal_tenant_id=settings.public_learner_tenant_id,
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
                scoring=args.scoring,
                approver=args.approver,
                issue=args.issue,
                reason=args.reason,
                tenant_id=args.tenant_id,
                every_workspace=bool(args.every_workspace),
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
