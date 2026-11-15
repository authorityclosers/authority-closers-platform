"""Take the coach out of the test world's TEST workspaces (approved data change).

The orchestrator, 15 Nov 2026, on the owner's approval for the test world (Pulse 54265ec8): the
TEST workspaces must not take in a real colleague. The first dev build added the sales coach
(``admin_email``) as an admin of TEST · Sahyadri Homes, TEST · Suryoday Solar and TEST · Kavach
Insurance Advisors; the generator now adds none (``admin_email`` equal to the owner's), so this
removes the coach from the workspaces already built, through the app's own member removal
(``OrganisationService.remove_member`` as an operator: the membership ends, its row and history
stay, and the app writes ``organisation.member_removed``), plus one audit event per workspace
naming the approver and the approval.

The workspaces are found by the build's own command id (sandbox-organisations.py makes each
organisation's ``creation_command_id`` as uuid5(build command id, "organisation:<key>")), so
nothing else can be touched, and each must be named "TEST · …". The coach must be an admin
there; an owner or any other role is refused. A dry run (the default) makes the change in its
transaction, prints before and after, and rolls back; ``--apply`` commits. A rerun changes
nothing.

Run where sandbox-organisations.py runs (dev: as root with the dev-live API's settings):
    $SLOT/.venv/bin/python scripts/data-changes/test-world-remove-coach.py '<input>' [--apply]
input (JSON text or a file): {"command_id", "build_command_id", "approver_email",
    "coach_email", "issue", "organisations"?: ["sahyadri", "suryoday", "kavach"]}
Prints the workspaces' names and masked emails; never anything else about a person.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.settings import get_settings
from ac_platform.audit.service import append_audit_event
from ac_platform.identity.models import Person
from ac_platform.organisations.service import OrganisationService
from ac_platform.tenancy.models import Membership, Organisation, Tenant

Mode = Literal["dry-run", "apply"]
ACTION = "organisation.test_world_coach_removed"
KEYS = ("sahyadri", "suryoday", "kavach")
REQUIRED = ("command_id", "build_command_id", "approver_email", "coach_email", "issue")
TEST_PREFIX = "TEST · "


def _refuse(reason: str, **extra: Any) -> SystemExit:
    return SystemExit(json.dumps({"refused": reason, **extra}))


def mask(email: str | None) -> str:
    if not email or "@" not in email:
        return "[none]"
    local, domain = email.rsplit("@", 1)
    return f"{local[:1]}***@{domain}"


def spec_of(raw: str) -> dict[str, Any]:
    text = raw if raw.lstrip().startswith("{") else Path(raw).read_text(encoding="utf-8")
    body = dict(json.loads(text))
    missing = [key for key in REQUIRED if not body.get(key)]
    if missing:
        raise _refuse("missing_input", fields=missing)
    UUID(str(body["command_id"]))
    UUID(str(body["build_command_id"]))
    keys = list(body.get("organisations") or KEYS)
    if any(key not in KEYS for key in keys):
        raise _refuse("unknown_organisation", known=list(KEYS))
    coach = str(body["coach_email"]).strip().lower()
    if coach == str(body["approver_email"]).strip().lower():
        raise _refuse("coach_is_the_approver")
    return {**body, "organisations": keys}


def organisation_command(build: UUID, key: str) -> UUID:
    """The creation command id sandbox-organisations.py gives the organisation ``key``."""
    return uuid5(build, f"organisation:{key}")


async def _person(db: AsyncSession, email: str) -> Person | None:
    wanted = email.strip().lower()
    found: Person | None = await db.scalar(select(Person).where(func.lower(Person.email) == wanted))
    return found


async def _roles(db: AsyncSession, tenant_id: UUID) -> list[tuple[str, str]]:
    rows = await db.execute(
        select(Membership.role, Person.email)
        .join(Person, Person.id == Membership.person_id)
        .where(Membership.tenant_id == tenant_id, Membership.ended_at.is_(None))
        .order_by(Membership.role, Person.email)
    )
    return [(role, mask(email)) for role, email in rows.all()]


async def run(
    db: AsyncSession, spec: dict[str, Any], *, boundaries: tuple[UUID, UUID]
) -> list[dict[str, Any]]:
    approver = await _person(db, spec["approver_email"])
    if approver is None:
        raise _refuse("approver_not_found")
    coach = await _person(db, spec["coach_email"])
    base = UUID(spec["command_id"])
    build = UUID(spec["build_command_id"])
    service = OrganisationService(
        db, operations_tenant_id=boundaries[0], public_learner_tenant_id=boundaries[1]
    )
    reports: list[dict[str, Any]] = []
    for key in spec["organisations"]:
        row = (
            await db.execute(
                select(Organisation.tenant_id, Tenant.name)
                .join(Tenant, Tenant.id == Organisation.tenant_id)
                .where(Organisation.creation_command_id == organisation_command(build, key))
            )
        ).one_or_none()
        if row is None:
            reports.append({"organisation": key, "status": "not_found"})
            continue
        tenant_id, name = row
        if not str(name).startswith(TEST_PREFIX):
            raise _refuse("not_a_test_workspace", organisation=key)
        report: dict[str, Any] = {"organisation": name, "before": await _roles(db, tenant_id)}
        member = None
        if coach is not None:
            member = await db.scalar(
                select(Membership).where(
                    Membership.tenant_id == tenant_id,
                    Membership.person_id == coach.id,
                    Membership.ended_at.is_(None),
                )
            )
        if coach is None or member is None:
            report["status"] = "coach_not_a_member"
        elif member.role != "admin":
            raise _refuse("coach_is_not_an_admin_here", organisation=name, role=member.role)
        else:
            await service.remove_member(
                tenant_id,
                coach.id,
                uuid5(base, f"remove-coach:{key}"),
                actor_person_id=approver.id,
                operator_reference=f"approved-data-change:{spec['issue']}"[:200],
            )
            await append_audit_event(
                db,
                tenant_id=tenant_id,
                actor_person_id=approver.id,
                actor_type="operator",
                action=ACTION,
                resource_type="tenant",
                resource_id=tenant_id,
                request_id=str(uuid5(base, f"audit:{key}")),
                reason=f"Approved ({spec['issue']}): no real colleague in a TEST workspace"[:500],
                payload={"issue": spec["issue"], "removed": mask(spec["coach_email"])},
            )
            await db.flush()
            report["status"] = "removed"
        report["after"] = await _roles(db, tenant_id)
        reports.append(report)
    return reports


async def main(raw: str, mode: Mode) -> int:
    spec = spec_of(raw)
    settings = get_settings()
    if settings.operations_tenant_id is None or settings.public_learner_tenant_id is None:
        raise _refuse("tenant_boundaries_not_configured")
    boundaries = (settings.operations_tenant_id, settings.public_learner_tenant_id)
    engine = create_async_engine(settings.database_url, hide_parameters=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            try:
                reports = await run(db, spec, boundaries=boundaries)
            except BaseException:
                await db.rollback()
                raise
            if mode == "apply":
                await db.commit()
            else:
                await db.rollback()
    finally:
        await engine.dispose()
    print(json.dumps({"mode": mode, "approval": spec["issue"], "organisations": reports}))
    return 0


if __name__ == "__main__":
    flags = {arg for arg in sys.argv[1:] if arg.startswith("--")}
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    if len(args) != 1 or flags - {"--apply"}:
        raise SystemExit("usage: test-world-remove-coach.py '<input JSON or file>' [--apply]")
    raise SystemExit(asyncio.run(main(args[0], "apply" if "--apply" in flags else "dry-run")))
