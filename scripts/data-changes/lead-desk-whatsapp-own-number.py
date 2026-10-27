#!/usr/bin/env python3
"""Connect an organisation's own WhatsApp number, with AC's own system-user token.

Owner, 27 Oct 2026: "WhatsApp for AC's org now on the same number" (the company
number calls go out from). AC uses its own Meta app with its own WhatsApp Business
Account, so it is a direct developer: its system user grants the app the WhatsApp
permissions, and no App Review or Embedded Signup is needed (App Review is only for
other businesses' numbers). This does what Embedded Signup's callback does
(``whatsapp.inbox.connect_number``) with that token:
- it subscribes the WhatsApp Business Account to the app;
- it registers the number for the Cloud API, with a PIN Sales X-Ray keeps sealed;
- it keeps the number for the organisation, the token sealed like any other;
- it brings in the account's templates.

Any environment, as an owner-approved data change (AGENTS.md): dry run unless
--apply; one transaction; one audit event naming the approver and the issue. In
production it also needs --snapshot (the database snapshot taken first). The token is
read from ``AC_WHATSAPP_OWN_SYSTEM_TOKEN`` (``infisical run`` for this one run) and
never printed. Prints ids and display numbers only.

    set -a; . /etc/authority-closers/<environment>/api-live.env; set +a
    infisical run --env=<env> --path=<the WhatsApp path> -- <venv python> \\
      scripts/data-changes/lead-desk-whatsapp-own-number.py \\
      --org <organisation tenant id> --by <owner or admin email in it> \\
      --waba-id <id> --phone-number-id <id> --approver <name> --issue <ref> \\
      [--snapshot <id>] [--apply]

Then run the first-day check (scripts/ops/whatsapp-day-one-check.py).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.settings import Settings
from ac_platform.audit.service import AuditRepository
from ac_platform.identity.models import Person
from ac_platform.lead_desk.models import LeadWhatsAppNumber
from ac_platform.lead_desk.store import LeadDesk, Viewer, person_name
from ac_platform.lead_desk.whatsapp import cloud
from ac_platform.lead_desk.whatsapp import inbox as wa_inbox
from ac_platform.tenancy.models import Membership, Organisation

TOKEN_ENV = "AC_WHATSAPP_OWN_SYSTEM_TOKEN"  # noqa: S105 - a name, never a value
ACTION = "lead_desk.whatsapp.own_number_connected"
META_ID = re.compile(r"^[0-9]{5,32}$")


async def change(
    db: AsyncSession,
    *,
    environment: str,
    org: UUID,
    by: str,
    waba_id: str,
    phone_number_id: str,
    approver: str,
    issue: str,
    snapshot: str | None,
    apply: bool,
    token: str | None,
    api: Any = None,
) -> dict[str, Any]:
    if not (META_ID.fullmatch(waba_id) and META_ID.fullmatch(phone_number_id)):
        raise SystemExit("--waba-id and --phone-number-id are Meta's numeric ids.")
    if environment == "production" and apply and not (snapshot or "").strip():
        raise SystemExit("Production: take a database snapshot first and pass --snapshot.")
    if not token:
        raise SystemExit(f"{TOKEN_ENV} is empty: run this inside infisical run.")
    cfg = cloud.config()
    if cfg is None:
        raise SystemExit("This API's WhatsApp settings (AC_WHATSAPP_*) aren't loaded.")
    if await db.get(Organisation, org) is None:
        raise SystemExit("That organisation isn't here.")
    found = (
        await db.execute(
            select(Person, Membership.role)
            .join(Membership, Membership.person_id == Person.id)
            .where(
                func.lower(Person.email) == by.strip().lower(),
                Membership.tenant_id == org,
                Membership.status == "active",
                Membership.ended_at.is_(None),
                Membership.role.in_(("owner", "admin")),
            )
        )
    ).first()
    if found is None:
        raise SystemExit("--by must be an active owner or admin of that organisation.")
    person, role = found
    client = api or cloud.Cloud(cfg)
    facts = await client.number(phone_number_id, token)

    def numbers_now(rows: list[LeadWhatsAppNumber]) -> list[dict[str, str]]:
        return [
            {"id": str(row.id), "number": row.display_number, "status": row.status} for row in rows
        ]

    result: dict[str, Any] = {
        "run_id": str(uuid4()),
        "environment": environment,
        "issue": issue,
        "approver": approver,
        "snapshot": snapshot,
        "organisation": str(org),
        "connected_by": person_name(person),
        "waba_id": waba_id,
        "phone_number_id": phone_number_id,
        "number": facts.get("display_number"),
        "verified_name": facts.get("verified_name"),
        "before": numbers_now(await wa_inbox.numbers(db, org)),
        "applied": False,
    }
    if not apply:
        result["would"] = (
            "subscribe the account to the app, register the number, keep it, sync templates"
        )
        return result
    now = datetime.now(UTC)
    desk = LeadDesk(
        db, Viewer(person_id=person.id, tenant_id=org, role=role, name=person_name(person)), now=now
    )
    row = await wa_inbox.connect_number(
        desk, cfg, client, token, waba_id=waba_id, phone_number_id=phone_number_id, register=True
    )
    templates = await wa_inbox.sync_templates(db, cfg, client, row, now=now)
    await AuditRepository(db).append(
        tenant_id=org,
        actor_person_id=person.id,
        action=ACTION,
        resource_type="lead_desk_whatsapp_number",
        resource_id=str(row.id),
        payload={
            "run_id": result["run_id"],
            "waba_id": waba_id,
            "phone_number_id": phone_number_id,
            "approver": approver,
            "issue": issue,
            "snapshot": snapshot,
        },
        reason=f"The organisation's own WhatsApp number, approved by {approver} ({issue})",
        now=now,
    )
    result.update(
        applied=True, after=numbers_now(await wa_inbox.numbers(db, org)), templates=templates
    )
    return result


async def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--org", type=UUID, required=True)
    parser.add_argument("--by", required=True, help="an owner or admin email in the org")
    parser.add_argument("--waba-id", required=True)
    parser.add_argument("--phone-number-id", required=True)
    parser.add_argument("--approver", required=True)
    parser.add_argument("--issue", required=True)
    parser.add_argument("--snapshot", help="production: the snapshot taken first")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    engine = create_async_engine(settings.database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db, db.begin():
            result = await change(
                db,
                environment=settings.environment,
                org=args.org,
                by=args.by,
                waba_id=args.waba_id,
                phone_number_id=args.phone_number_id,
                approver=args.approver,
                issue=args.issue,
                snapshot=args.snapshot,
                apply=args.apply,
                token=os.environ.get(TOKEN_ENV),
            )
    finally:
        await engine.dispose()
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
