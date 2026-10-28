#!/usr/bin/env python3
"""Queue 20 fictional password emails through the real outbox; fake adapter only."""

import asyncio
import json
import os
import secrets
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ac_platform.audit.service import AuditRepository
from ac_platform.http.auth import _password_email_event
from ac_platform.identity.models import Session
from ac_platform.identity.password_auth import PasswordIdentityService
from ac_platform.kernel.authz import ActorContext
from ac_platform.outbox.repository import OutboxRepository, RecoveryStateRepository
from ac_platform.tenancy.models import Tenant


async def main():
    root = Path("/fixture")
    if (
        not (root / "FICTIONAL-ONLY").is_file()
        or os.environ.get("AC_EMAIL_PROVIDER", "fake") != "fake"
    ):
        raise SystemExit("Fictional fixture and fake adapter required")
    if "@pgbouncer:6432/ac_platform" not in os.environ["AC_DATABASE_URL"]:
        raise SystemExit("Isolated pooler required")
    ids = json.loads((root / "fixture-ids.json").read_text())
    owner = UUID(ids["owner"])
    operations = UUID(os.environ["AC_OPERATIONS_TENANT_ID"])
    engine = create_async_engine(os.environ["AC_DATABASE_URL"], hide_parameters=True)
    async with AsyncSession(engine) as db, db.begin():
        if await db.get(Tenant, operations) is None:
            db.add(Tenant(id=operations, slug="fictional-operations", name="Fictional Operations"))
            await db.flush()
        session = await db.scalar(select(Session).where(Session.person_id == owner))
        actor = ActorContext(
            owner,
            session.id,
            operations,
            frozenset({"recovery_reconcile", "global_recovery_reconcile"}),
        )
        await RecoveryStateRepository(db).reconcile(
            actor=actor,
            reason="Fictional rehearsal only; fake email and blocked egress",
            audit=AuditRepository(db),
            operations_tenant_id=operations,
        )
        identity = PasswordIdentityService(db, token_secret=os.environ["AC_EMAIL_CHALLENGE_SECRET"])
        for i in range(20):
            registration = await identity.register(
                email=f"job-{uuid4().hex}@example.test",
                first_name=f"Fictional Job {i}",
                whatsapp_number="+14155550100",
                password=secrets.token_urlsafe(32),
                consent_version="fictional-rehearsal-v1",
            )
            challenge = registration.challenge
            event = _password_email_event(
                challenge_id=challenge.challenge_id,
                person_id=challenge.person_id,
                kind=challenge.kind.value,
            )
            await OutboxRepository(db).enqueue(
                event, dedupe_key=f"fictional-job:{challenge.challenge_id}"
            )
    await engine.dispose()
    print("20 fictional verification events queued; fake email adapter only")


if __name__ == "__main__":
    asyncio.run(main())
