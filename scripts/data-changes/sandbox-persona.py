"""One more fictional person, at a role below Owner, in an existing sandbox organisation
(approved data change).

Owner, 4 Nov 2026 (owner chat, through the orchestrator): "Approve, dev only" to adding one
fictional account to the dev sandbox, then "Yes, as Admin": an organisation has exactly one
Owner and the owner's own account owns the sandbox, so the persona is an Admin. An Admin may
do everything an Owner may except pay and pass ownership on (tenancy/roles.py), so the test
robot and the design studio see the owner-side screens, the Team view first, without signing
in as the owner. In one transaction, through the app's own code:
  1. the person's account: a plus-alias of the owner's mailbox (so any mail reaches it),
     verified, with the scrypt verifier of a password given in the input (the password lives
     only in Infisical, made by sandbox-logins.py, never here); an account already there is
     used as it is;
  2. their membership at the role asked for (``OrganisationService.add_member``), only in an
     organisation flagged as a sandbox (``conversation_sandbox_organisations``), never as Owner;
  3. one audit event naming the approver and the approval.

A dry run (the default) makes the change in its transaction, reports it and rolls it back.
``--apply`` commits. A rerun finds the membership and changes nothing. ``--read`` reads the
organisation's people back in a read-only transaction.

Run with the backend's deployed settings, in the API container (read-only filesystem, so the
input goes inline):
    docker exec -i <api> python - '<input JSON>' [--apply | --read] < sandbox-persona.py
or with the backend's virtualenv and environment, the input in a file (mode 0600: it holds
a verifier).
input: {"command_id", "approver_email", "issue", "tenant_id", "email", "name",
        "role": "admin" | "manager" | "member", "password_hash"?: a scrypt verifier}
Prints roles, names and masked emails; never a password or a verifier.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import UTC, datetime
from typing import Any, Final, Literal
from uuid import UUID, uuid5

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.settings import get_settings
from ac_platform.audit.service import append_audit_event
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
)
from ac_platform.identity.models import PasswordCredential, Person
from ac_platform.identity.repositories import AsyncSqlAlchemyIdentityRepository
from ac_platform.identity.services import PersonSnapshot
from ac_platform.organisations.service import OrganisationService
from ac_platform.tenancy.models import Membership, Tenant

Mode = Literal["dry-run", "apply", "read"]
ACTION: Final = "organisations.sandbox_persona_data_change"
# Never "owner": an organisation has exactly one, and passing it on is the owner's own act.
ROLES: Final = ("admin", "manager", "member")
VERIFIER: Final = re.compile(r"\Ascrypt\$ln=15,r=8,p=1\$[A-Za-z0-9_-]{16,}\$[A-Za-z0-9_-]{32,}\Z")


def _refuse(reason: str, **extra: Any) -> SystemExit:
    return SystemExit(json.dumps({"refused": reason, **extra}))


def spec_of(raw: str) -> dict[str, Any]:
    """The input, checked: inline JSON or a file."""
    if raw.lstrip().startswith("{"):
        body = dict(json.loads(raw))
    else:
        with open(raw, encoding="utf-8") as file:
            body = dict(json.load(file))
    needed = ("command_id", "approver_email", "issue", "tenant_id", "email", "name", "role")
    missing = [name for name in needed if not body.get(name)]
    if missing:
        raise _refuse("missing_input", fields=missing)
    UUID(str(body["command_id"]))
    UUID(str(body["tenant_id"]))
    email = str(body["email"]).strip().lower()
    local, _, domain = email.partition("@")
    if not domain or "+" not in local:
        raise _refuse("email_not_a_plus_alias")
    role = str(body["role"]).strip().lower()
    if role not in ROLES:
        raise _refuse("role_not_allowed", allowed=list(ROLES))
    name = " ".join(str(body["name"]).split())
    if not 2 <= len(name) <= 80:
        raise _refuse("name_out_of_range")
    verifier = body.get("password_hash")
    if verifier is not None and not VERIFIER.match(str(verifier)):
        raise _refuse("password_hash_not_a_verifier")
    return {
        **body,
        "email": email,
        "role": role,
        "name": name,
        "password_hash": None if verifier is None else str(verifier),
    }


def _mask(email: str | None) -> str:
    if not email or "@" not in email:
        return "[none]"
    local, domain = email.rsplit("@", 1)
    return f"{local[:1]}***@{domain}"


async def _person(db: AsyncSession, email: str) -> Person | None:
    found: Person | None = await db.scalar(
        select(Person).where(func.lower(Person.email) == email.strip().lower())
    )
    return found


async def _account(db: AsyncSession, spec: dict[str, Any], now: datetime) -> tuple[UUID, str]:
    """The person's account: found, or made verified with its password verifier."""
    found = await _person(db, spec["email"])
    if found is not None:
        return found.id, "found"
    if spec["password_hash"] is None:
        raise _refuse("password_hash_missing", email=_mask(spec["email"]))
    person_id = uuid5(UUID(str(spec["command_id"])), f"person:{spec['email']}")
    await AsyncSqlAlchemyIdentityRepository(db).save_person(
        PersonSnapshot(
            id=person_id, email=spec["email"], display_name=spec["name"], email_verified_at=now
        )
    )
    db.add(PasswordCredential(person_id=person_id, password_hash=spec["password_hash"]))
    await db.flush()
    return person_id, "made"


async def _role(db: AsyncSession, tenant_id: UUID, person_id: UUID) -> str | None:
    role: str | None = await db.scalar(
        select(Membership.role).where(
            Membership.tenant_id == tenant_id,
            Membership.person_id == person_id,
            Membership.ended_at.is_(None),
        )
    )
    return role


async def people(db: AsyncSession, tenant_id: UUID) -> list[dict[str, str]]:
    """The organisation's people as the app holds them: role, name and masked email."""
    rows = (
        await db.execute(
            select(Membership.role, Person.display_name, Person.email)
            .join(Person, Person.id == Membership.person_id)
            .where(Membership.tenant_id == tenant_id, Membership.ended_at.is_(None))
            .order_by(Membership.role, Person.display_name)
        )
    ).all()
    return [
        {"role": str(role), "name": name or "", "email": _mask(email)} for role, name, email in rows
    ]


async def run(
    db: AsyncSession,
    spec: dict[str, Any],
    *,
    mode: Mode,
    now: datetime,
    boundaries: tuple[UUID, UUID],
) -> dict[str, Any]:
    """The change, its rehearsal, or its read-back, in the caller's transaction."""
    tenant_id = UUID(str(spec["tenant_id"]))
    command_id = uuid5(UUID(str(spec["command_id"])), "sandbox-persona")
    if mode == "read":
        await db.execute(text("SET TRANSACTION READ ONLY"))
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise _refuse("organisation_not_found")
    flagged = await db.scalar(
        select(ConversationSandboxOrganisation.tenant_id).where(
            ConversationSandboxOrganisation.tenant_id == tenant_id
        )
    )
    if flagged is None:
        raise _refuse("not_a_sandbox_organisation", organisation=tenant.name)
    report: dict[str, Any] = {
        "mode": mode,
        "organisation": tenant.name,
        "email": _mask(spec["email"]),
    }
    person = await _person(db, spec["email"])
    current = None if person is None else await _role(db, tenant_id, person.id)
    report["before"] = {
        "account": person is not None,
        "role": current,
        "people": await people(db, tenant_id),
    }
    if mode == "read":
        report["status"] = "read"
        return report
    if current is not None:
        if current == spec["role"]:
            report["status"] = "already_applied"
            return report
        raise _refuse("already_a_member_at_another_role", role=current)
    approver = await _person(db, spec["approver_email"])
    if approver is None:
        raise _refuse("approver_not_found")

    # 1. The account.
    person_id, state = await _account(db, spec, now)

    # 2. The membership, as an operator adds one.
    reference = f"approved-data-change:{spec['issue']}"[:160]
    why = f"Fictional sandbox {spec['role']} ({spec['issue']})"
    service = OrganisationService(
        db, operations_tenant_id=boundaries[0], public_learner_tenant_id=boundaries[1]
    )
    await service.add_member(
        tenant_id,
        person_id,
        spec["role"],
        command_id,
        operator_reference=reference,
        reason=why,
    )

    # 3. The audit event.
    await append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_person_id=approver.id,
        actor_type="operator",
        action=ACTION,
        resource_type="tenant",
        resource_id=tenant_id,
        request_id=str(uuid5(command_id, "audit")),
        reason=f"Owner approval ({spec['issue']}): fictional {spec['role']} in {tenant.name}",
        payload={
            "issue": spec["issue"],
            "command_id": str(command_id),
            "person_id": str(person_id),
            "role": spec["role"],
            "account": state,
        },
    )
    await db.flush()
    report["account"] = state
    report["command_id"] = str(command_id)
    report["after"] = {
        "role": await _role(db, tenant_id, person_id),
        "people": await people(db, tenant_id),
    }
    report["status"] = "applied" if mode == "apply" else "rehearsed_and_rolled_back"
    return report


async def execute(
    sessions: async_sessionmaker[AsyncSession],
    spec: dict[str, Any],
    *,
    mode: Mode,
    now: datetime,
    boundaries: tuple[UUID, UUID],
) -> dict[str, Any]:
    """One transaction: committed on apply, rolled back otherwise."""
    async with sessions() as db:
        try:
            report = await run(db, spec, mode=mode, now=now, boundaries=boundaries)
        except BaseException:
            await db.rollback()
            raise
        if mode == "apply":
            await db.commit()
        else:
            await db.rollback()
    return report


async def main(path: str, mode: Mode) -> int:
    spec = spec_of(path)
    settings = get_settings()
    if settings.operations_tenant_id is None or settings.public_learner_tenant_id is None:
        raise _refuse("tenant_boundaries_not_configured")
    engine = create_async_engine(settings.database_url, hide_parameters=True)
    try:
        report = await execute(
            async_sessionmaker(engine, expire_on_commit=False),
            spec,
            mode=mode,
            now=datetime.now(UTC),
            boundaries=(settings.operations_tenant_id, settings.public_learner_tenant_id),
        )
    finally:
        await engine.dispose()
    print(json.dumps({"approval": spec["issue"], **report}, default=str))
    return 0


if __name__ == "__main__":
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    chosen: Mode = "apply" if "--apply" in flags else "read" if "--read" in flags else "dry-run"
    raise SystemExit(asyncio.run(main(args[0], chosen)))
