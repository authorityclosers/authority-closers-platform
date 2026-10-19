"""Provision AC staff accounts on production, linked to the Google sign-in they already use.

Owner order, 19 Oct 2026 (Suyash Kulkarni, chat): "Accept and do this from our end; they are our
own test ones, so activate accounts from backend ourselves and upload." For each staff member this
creates the person (email verified, no consent recorded: they accept the terms at their first
sign-in) and links the Google provider key they already use on staging, so "Sign in with Google"
lands in this account instead of creating a second one. Organisation invitations are accepted
separately, through the API, as each person.

Run inside the production API container with the deployed settings:
    docker exec -i <api> python - <input.json> [--apply] < provision-staff-production.py
input.json: {"approver_person_id", "tenant_id", "command_id", "staff": [{"email", "display_name",
"issuer", "subject"}]}. Dry run unless --apply; one transaction; one audit event per person.
Prints masked emails and ids only, never the provider subject.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import UTC, datetime
from uuid import UUID, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.application.settings import get_settings
from ac_platform.audit.service import append_audit_event
from ac_platform.identity.repositories import AsyncSqlAlchemyIdentityRepository
from ac_platform.identity.services import PersonSnapshot, ProviderIdentitySnapshot


def _mask(email: str) -> str:
    return re.sub(r"^(.{3}).*(@.*)$", r"\1***\2", email)


async def main(path: str, apply: bool) -> int:
    spec = json.load(open(path))
    command_id = UUID(spec["command_id"])
    tenant_id = UUID(spec["tenant_id"])
    approver = UUID(spec["approver_person_id"])
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    results = []
    try:
        async with async_sessionmaker(engine)() as db, db.begin():
            repo = AsyncSqlAlchemyIdentityRepository(db)
            now = datetime.now(UTC)
            for item in spec["staff"]:
                email = item["email"].strip().lower()
                person_id = uuid5(command_id, f"person:{email}")
                identity_id = uuid5(command_id, f"identity:{email}")
                by_email = (
                    await db.execute(
                        text("select id from persons where lower(email) = :e"), {"e": email}
                    )
                ).scalars().all()
                by_key = (
                    await db.execute(
                        text(
                            "select person_id from provider_identities"
                            " where issuer = :i and subject = :s"
                        ),
                        {"i": item["issuer"], "s": item["subject"]},
                    )
                ).scalars().all()
                if by_email or by_key:
                    already = set(by_email) | set(by_key)
                    status = "exists" if already == {person_id} else "refused_conflict"
                    results.append(
                        {"email": _mask(email), "status": status, "person_ids": sorted(map(str, already))}
                    )
                    continue
                results.append(
                    {"email": _mask(email), "status": "applied" if apply else "eligible", "person_id": str(person_id)}
                )
                if not apply:
                    continue
                await repo.save_person(
                    PersonSnapshot(
                        id=person_id,
                        email=email,
                        display_name=item.get("display_name"),
                        email_verified_at=now,
                    )
                )
                await repo.save_provider_identity(
                    ProviderIdentitySnapshot(
                        id=identity_id,
                        person_id=person_id,
                        issuer=item["issuer"],
                        subject=item["subject"],
                        created_at=now,
                    )
                )
                await append_audit_event(
                    db,
                    tenant_id=tenant_id,
                    actor_person_id=approver,
                    actor_type="operator",
                    action="identity.staff_account_provisioned",
                    resource_type="person",
                    resource_id=person_id,
                    request_id=str(uuid5(command_id, f"audit:{email}")),
                    reason="Owner order 19 Oct 2026: provision AC staff accounts linked to their Google sign-in",
                    payload={"email": _mask(email), "issuer": item["issuer"], "command_id": str(command_id)},
                )
            if any(r["status"] == "refused_conflict" for r in results):
                raise SystemExit(json.dumps({"refused": results}))
    finally:
        await engine.dispose()
    print(json.dumps({"mode": "apply" if apply else "dry-run", "results": results}))
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--apply"]
    raise SystemExit(asyncio.run(main(args[0], "--apply" in sys.argv[1:])))
