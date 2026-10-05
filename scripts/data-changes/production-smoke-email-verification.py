#!/usr/bin/env python3
"""AUT-398: preview/apply verification of the existing internal smoke fixture only."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from datetime import UTC, datetime
from typing import NoReturn
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.application.release_identity import require_baked_release_id
from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.identity.models import PasswordCredential, Person
from ac_platform.identity.services import normalize_email
from ac_platform.tenancy.learner_provisioning import AsyncLearnerProvisioningApplication
from ac_platform.tenancy.models import Membership, Tenant

OWNER = "ZyTZxLQfn8zFPFVZ5OjwisIX96Xmo4j0"
APPROVAL = "a64d5f9b-5c52-40d3-bee9-56e4e82527ff"
ACTION = "identity.production_smoke_email_verified"
APPROVED_PRIOR_CONSENT_VERSION = "ac-learner-terms-privacy-2026-09-13-v1"


class SmokeVerificationError(RuntimeError):
    """A bounded refusal that never includes confidential inputs."""


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise SmokeVerificationError("invalid arguments; use --help")


def _parser() -> argparse.ArgumentParser:
    parser = SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--environment", choices=("production",), required=True)
    parser.add_argument("--person-id", type=UUID, required=True)
    parser.add_argument("--approver", choices=(OWNER,), required=True)
    parser.add_argument("--approval-reference", choices=(APPROVAL,), required=True)
    parser.add_argument("--issue-reference", choices=("AUT-398",), required=True)
    for name in ("operator-reference", "run-reference", "command-id"):
        parser.add_argument(f"--{name}", type=UUID, required=True)
    parser.add_argument(
        "--recorded-consent-version",
        choices=(APPROVED_PRIOR_CONSENT_VERSION,),
        help="explicitly name the approved prior consent; must match the person's record",
    )
    parser.add_argument("--apply", action="store_true")
    return parser


def _settings(args: argparse.Namespace) -> Settings:
    if args.environment != "production" or os.getenv("AC_ENVIRONMENT") != "production":
        raise SmokeVerificationError("production runtime required")
    if not os.getenv("AC_DATABASE_URL", "").strip():
        raise SmokeVerificationError("injected database settings required")
    settings = Settings(_env_file=None)
    if settings.environment != "production":
        raise SmokeVerificationError("production runtime required")
    require_baked_release_id(settings.release_id)
    if (
        settings.operations_tenant_id is None
        or settings.public_learner_tenant_id is None
        or settings.operations_tenant_id == settings.public_learner_tenant_id
    ):
        raise SmokeVerificationError("distinct canonical audit and learner tenants required")
    if not (settings.learner_consent_version or "").strip():
        raise SmokeVerificationError("configured learner consent version required")
    return settings


def _email_from_stdin() -> str:
    # Root pipes only AC_SMOKE_EMAIL from the protected account file. No email
    # selector exists on argv, and this tool never opens the credential file.
    if sys.stdin.isatty():
        raise SmokeVerificationError("confidential smoke email input required")
    raw = sys.stdin.read(1024)
    if len(raw) > 400:
        raise SmokeVerificationError("bounded confidential input required")
    values = shlex.split(raw)
    if len(values) != 1:
        raise SmokeVerificationError("one confidential input required")
    email = normalize_email(values[0]).lower()
    if not email.endswith("+ac-qa-production@authorityclosers.com"):
        raise SmokeVerificationError("internal production fixture required")
    return email


def _state(person: Person, *, has_membership: bool) -> dict[str, object]:
    return {
        "email_verified": person.email_verified_at is not None,
        "revision": person.revision,
        "learner_membership": "present" if has_membership else "absent",
    }


async def _change(
    session: AsyncSession, settings: Settings, args: argparse.Namespace, email: str
) -> dict[str, object]:
    # Apply serializes on the person before inspecting any command receipt.
    query = select(Person).where(func.lower(Person.email) == email).limit(2)
    if args.apply:
        query = query.with_for_update()
    people = list(await session.scalars(query))
    if len(people) != 1:
        raise SmokeVerificationError("exactly one existing target required")
    audit_tenant_id = settings.operations_tenant_id
    learner_tenant_id = settings.public_learner_tenant_id
    if audit_tenant_id is None or learner_tenant_id is None or audit_tenant_id == learner_tenant_id:
        raise SmokeVerificationError("distinct canonical audit and learner tenants required")
    person = people[0]
    if (
        person.id != args.person_id
        or person.status != "active"
        or person.first_name != "Rowan Fixture"
        or person.display_name != "Rowan Fixture"
        or person.consented_at is None
        or not person.consent_version
    ):
        raise SmokeVerificationError("pinned active internal fixture required")
    configured_version = (settings.learner_consent_version or "").strip()
    named_version = args.recorded_consent_version
    if not configured_version or (
        named_version is not None
        and (
            named_version != APPROVED_PRIOR_CONSENT_VERSION
            or named_version != person.consent_version
        )
    ):
        raise SmokeVerificationError("exact configured or explicitly named prior consent required")
    consent_version = named_version or configured_version
    if person.consent_version != consent_version:
        raise SmokeVerificationError("exact configured or explicitly named prior consent required")
    consent = {
        "recorded_version": person.consent_version,
        "configured_version": configured_version,
        "named_prior_version": named_version,
    }
    # Select only the credential ID, never its password verifier.
    if (
        await session.scalar(
            select(PasswordCredential.id).where(PasswordCredential.person_id == person.id)
        )
        is None
    ):
        raise SmokeVerificationError("existing password fixture required")
    members = list(
        await session.scalars(select(Membership).where(Membership.person_id == person.id))
    )
    if any(
        row.tenant_id != learner_tenant_id or row.role != "learner" or row.status != "active"
        for row in members
    ):
        raise SmokeVerificationError("unexpected fixture memberships")
    # Identity's global operator audit uses operations, as in email_login.py.
    # Verification provisions the public learner context only when applying.
    tenants = list(
        await session.scalars(
            select(Tenant).where(Tenant.id.in_([audit_tenant_id, learner_tenant_id]))
        )
    )
    if len(tenants) != 2 or any(row.status != "active" for row in tenants):
        raise SmokeVerificationError("active canonical audit and learner tenants required")
    attribution = {
        "approver": args.approver,
        "approval": args.approval_reference,
        "issue": args.issue_reference,
        "operator": str(args.operator_reference),
        "run": str(args.run_reference),
    }
    intent = {
        "person_id": str(person.id),
        "email_verified": True,
        "learner_tenant_id": str(learner_tenant_id),
        "required_consent_version": consent_version,
        **attribution,
    }
    if named_version is not None:
        intent["named_prior_consent_version"] = named_version
        intent["configured_consent_version"] = configured_version
    prior = list(
        await session.scalars(
            select(AuditEvent).where(AuditEvent.request_id == str(args.command_id)).limit(2)
        )
    )
    if prior and (
        len(prior) != 1
        or prior[0].action != ACTION
        or prior[0].tenant_id != audit_tenant_id
        or prior[0].resource_type != "person"
        or prior[0].resource_id != str(person.id)
        or prior[0].payload.get("intent") != intent
        or person.email_verified_at is None
        or not members
    ):
        raise SmokeVerificationError("command has conflicting intent or state")
    before = _state(person, has_membership=bool(members))
    before_timestamp = person.email_verified_at
    after: dict[str, object] = {
        "email_verified": True,
        "revision": person.revision + (0 if before["email_verified"] else 1),
        "learner_membership": "present" if members else "planned",
    }
    complete = bool(before["email_verified"] and members)
    status = "replayed" if prior else "already_verified" if complete else "eligible"
    if args.apply and status == "eligible":
        now = datetime.now(UTC)
        if person.email_verified_at is None:
            person.email_verified_at = now
            person.revision += 1
        await session.flush()
        await AsyncLearnerProvisioningApplication(session).ensure(
            person_id=person.id,
            tenant_id=learner_tenant_id,
            required_consent_version=consent_version,
        )
        after = _state(person, has_membership=True)
        await AuditRepository(session).append(
            tenant_id=audit_tenant_id,
            actor_person_id=None,
            actor_type="operator",
            action=ACTION,
            resource_type="person",
            resource_id=person.id,
            request_id=str(args.command_id),
            reason="AUT-398: owner-approved internal production smoke verification",
            payload={
                "intent": intent,
                "consent": consent,
                "before": {
                    **before,
                    "email_verified_at": before_timestamp.isoformat() if before_timestamp else None,
                },
                "after": {**after, "email_verified_at": person.email_verified_at.isoformat()},
            },
            now=now,
        )
        status = "applied"
    return {
        "environment": "production",
        "release_id": settings.release_id,
        "mode": "apply" if args.apply else "dry_run",
        "person_id": str(person.id),
        "audit_tenant_id": str(audit_tenant_id),
        "command_id": str(args.command_id),
        "attribution": attribution,
        "consent": consent,
        "status": status,
        "before": before,
        "after": after,
    }


async def _run(args: argparse.Namespace) -> int:
    settings = _settings(args)
    email = _email_from_stdin()
    engine = create_async_engine(settings.database_url, echo=False, hide_parameters=True)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with sessions() as session, session.begin():
            if not args.apply:
                await session.execute(text("SET TRANSACTION READ ONLY"))
            output = await _change(session, settings, args, email)
        print(json.dumps(output, sort_keys=True))
        return 0
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    try:
        return run_async(_run(_parser().parse_args(argv)))
    except (ValueError, RuntimeError, OSError, SQLAlchemyError):
        print("smoke verification refused or failed; no changes committed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
