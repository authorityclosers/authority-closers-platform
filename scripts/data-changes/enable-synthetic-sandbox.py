#!/usr/bin/env python3
"""Exact staging AC Sandbox opt-in; dry-run by default, for the named staging operator."""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.application.settings import Settings
from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
)
from ac_platform.tenancy.models import Membership, Organisation, Tenant

TARGET = UUID("90ec1979-0d85-4829-ba8d-cabde2a9a9d3")


async def execute(*, settings: Settings, approver: UUID, approval: str, apply: bool) -> dict:
    if settings.environment != "staging":
        raise ValueError("This exact data change supports staging AC Sandbox only.")
    engine = create_async_engine(settings.database_url, echo=False, hide_parameters=True)
    run_id = uuid4()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db, db.begin():
            tenant = await db.scalar(select(Tenant).where(Tenant.id == TARGET).with_for_update())
            organisation = await db.get(Organisation, TARGET)
            member = await db.get(Membership, (TARGET, approver))
            if (
                tenant is None
                or tenant.name != "AC Sandbox"
                or tenant.status != "active"
                or organisation is None
                or member is None
                or member.role != "owner"
                or member.status != "active"
                or member.ended_at is not None
            ):
                raise ValueError(
                    "The exact active AC Sandbox and its current approving owner are required."
                )
            existing = await db.get(ConversationSandboxOrganisation, TARGET)
            result = {
                "run_id": str(run_id),
                "tenant_id": str(TARGET),
                "environment": "staging",
                "approver_person_id": str(approver),
                "issue": "AUT-1676",
                "approval_reference": approval,
                "before": existing is not None,
                "after": True,
                "applied": apply,
            }
            if apply:
                now = datetime.now(UTC)
                if existing is None:
                    db.add(
                        ConversationSandboxOrganisation(
                            tenant_id=TARGET,
                            approved_by_person_id=approver,
                            approval_reference=approval,
                            created_at=now,
                        )
                    )
                    await db.flush()
                await AuditRepository(db).append(
                    tenant_id=TARGET,
                    actor_person_id=approver,
                    actor_type="operator",
                    action="conversation.sandbox_flag_approved",
                    resource_type="conversation_sandbox_organisation",
                    resource_id=TARGET,
                    payload={
                        "run_id": str(run_id),
                        "issue": "AUT-1676",
                        "approval_reference": approval,
                    },
                    now=now,
                )
            return result
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approver-person-id", type=UUID, required=True)
    parser.add_argument("--approval-reference", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not 1 <= len(args.approval_reference) <= 160:
        parser.error("Provide a bounded recorded owner approval reference.")
    # Runtime injection only. This script never reads the server secrets directory.
    try:
        result = asyncio.run(
            execute(
                settings=Settings(),
                approver=args.approver_person_id,
                approval=args.approval_reference,
                apply=args.apply,
            )
        )
    except Exception:
        parser.exit(2, "Sandbox opt-in failed; credentials and database details are withheld.\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
