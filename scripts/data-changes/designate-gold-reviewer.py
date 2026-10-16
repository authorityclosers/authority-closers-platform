#!/usr/bin/env python3
"""Owner-approved ecff5661: Dipak's independent gold-reviewer designation.

Dry-run by default. Uses runtime-injected Settings only. The production operator
must take a snapshot and show the dry-run before applying after the feature ships.
No learner membership, enrollment, verification bypass, invitation mail or session
is created. A missing Person can be created unverified only with --create-person;
the existing reviewer mailbox flow still verifies that identity.
"""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.application.settings import Settings
from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.gold_review_models import GoldReviewer
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Membership

REVIEWER = "dipak@authorityclosers.com"
APPROVER = "admin@authorityclosers.com"
ISSUE = "ecff5661"


async def change(database, *, operations_tenant_id: UUID, apply: bool, create_person: bool) -> dict:
    now, run_id = datetime.now(UTC), uuid4()
    person = await database.scalar(
        select(Person).where(func.lower(Person.email) == REVIEWER).with_for_update()
    )
    before_person = person is not None
    existing = await database.get(GoldReviewer, person.id) if person else None
    result = {
        "run_id": str(run_id),
        "reviewer": REVIEWER,
        "approver": "Suyash",
        "approver_email": APPROVER,
        "issue": ISSUE,
        "before": {
            "person_exists": before_person,
            "person_id": str(person.id) if person else None,
            "gold_reviewer": existing is not None and existing.revoked_at is None,
        },
        "after": {
            "person_exists": before_person or create_person,
            "gold_reviewer": before_person or create_person,
        },
        "applied": False,
    }
    if person is None and not create_person:
        result["blocked"] = (
            "No existing Person. Inspect first; --create-person creates "
            "only an unverified reviewer identity."
        )
        return result
    if person is not None and person.status != "active":
        raise ValueError("Dipak's canonical Person is not active; no status is changed.")
    approver = await database.scalar(select(Person).where(func.lower(Person.email) == APPROVER))
    member = (
        await database.get(Membership, (operations_tenant_id, approver.id)) if approver else None
    )
    if (
        approver is None
        or approver.status != "active"
        or approver.email_verified_at is None
        or member is None
        or member.status != "active"
        or member.ended_at is not None
        or member.role not in {"admin", "owner"}
    ):
        raise ValueError(
            f"Verified approver {APPROVER} and an active admin/owner membership in the "
            "configured AC operations workspace are required. No membership is created."
        )
    if not apply:
        return result
    if person is None:
        person = Person(
            id=uuid4(), email=REVIEWER, status="active", display_name="Dipak", created_at=now
        )
        database.add(person)
        await database.flush()
    if existing is None:
        database.add(GoldReviewer(person_id=person.id, designated_by=approver.id, created_at=now))
    elif existing.revoked_at is not None:
        existing.revoked_at, existing.designated_by = None, approver.id
    await database.flush()
    await AuditRepository(database).append(
        tenant_id=operations_tenant_id,
        actor_person_id=approver.id,
        action="conversation.gold_reviewer_data_change",
        resource_type="conversation_gold_reviewer",
        resource_id=person.id,
        payload={
            "run_id": str(run_id),
            "issue": ISSUE,
            "approver": "Suyash",
            "approver_email": APPROVER,
            "before": result["before"],
            "after": result["after"],
        },
        reason="Owner approval 16 Oct 2026 ~06:17Z: Dipak reviewer account, dev and production",
        now=now,
    )
    result["after"]["person_id"] = str(person.id)
    result["applied"] = True
    return result


async def execute(args) -> dict:
    settings = Settings()
    if settings.environment != args.environment or settings.operations_tenant_id is None:
        raise ValueError(
            "Select the exact runtime environment and configured AC operations workspace."
        )
    engine = create_async_engine(settings.database_url, echo=False, hide_parameters=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db, db.begin():
            if args.inspect:
                person = await db.scalar(select(Person).where(func.lower(Person.email) == REVIEWER))
                return {
                    "environment": settings.environment,
                    "email": REVIEWER,
                    "exists": person is not None,
                    "person_id": str(person.id) if person else None,
                    "status": person.status if person else None,
                    "verified": person is not None and person.email_verified_at is not None,
                }
            result = await change(
                db,
                operations_tenant_id=settings.operations_tenant_id,
                apply=args.apply,
                create_person=args.create_person,
            )
            result["environment"] = settings.environment
            return result
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=("development", "production"), required=True)
    parser.add_argument("--inspect", action="store_true", help="read only: canonical Person lookup")
    parser.add_argument("--create-person", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.inspect and (args.apply or args.create_person):
        parser.error("--inspect is read only")
    print(json.dumps(asyncio.run(execute(args)), sort_keys=True))


if __name__ == "__main__":
    main()
