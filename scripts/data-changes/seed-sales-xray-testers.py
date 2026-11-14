#!/usr/bin/env python3
"""Seed the Sales X-Ray tester list with the Play group's members (owner, 13 Nov 2026).

The closed test "Closed testing - Alpha" uses the Google Group salesxray-testers@. Its members
when the list began go in as "listed" (with what production showed for each account then:
account yes/no, app sessions, first and last app session, app version, last web session,
bug reports) plus "added_to_group" (via seed), so Admin -> Testers starts with their real
stages on every environment. A member the owner already emailed by hand is recorded as
"emailed" (via gmail) at the time given. Nobody is emailed by this script.

Input: a CSV that never enters git (personal data), one row per member, with the columns
email,name,has_account,app_sessions,first_app_at,last_app_at,app_version,web_last_at,bugs
(read from production through the logged read-only path), and optionally --emailed-by-hand
<file> with "email,ISO time" lines.

Dry-run by default; --apply writes everything in one transaction with an audit event naming
the approver and the issue. Idempotent: a member already on the list is left as they are.
On production, take a snapshot and show the dry-run first.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.settings import Settings
from ac_platform.audit.service import AuditRepository
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Membership
from ac_platform.testers.models import SalesXrayTesterEvent
from ac_platform.testers.store import normal_email

APPROVER = "admin@authorityclosers.com"
FACT_INTS = ("app_sessions", "bugs")
FACT_TIMES = ("first_app_at", "last_app_at", "web_last_at")


def _time(value: str) -> str | None:
    text = (value or "").strip()
    if not text or text == "-":
        return None
    moment = datetime.fromisoformat(text.replace("Z", "+00:00").replace(" ", "T", 1))
    moment = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat()


def read_members(path: Path) -> list[dict[str, Any]]:
    members: dict[str, dict[str, Any]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            email = normal_email(row["email"])
            facts: dict[str, Any] = {
                "has_account": (row.get("has_account") or "").strip().lower() in ("t", "true", "1")
            }
            for key in FACT_INTS:
                facts[key] = int((row.get(key) or "0").strip() or 0)
            for key in FACT_TIMES:
                facts[key] = _time(row.get(key) or "")
            version = (row.get("app_version") or "").strip()
            facts["app_version"] = version[:24] if version and version != "-" else None
            facts["read_from"] = "production"
            name = " ".join((row.get("name") or "").split())[:120] or None
            members[email] = {"email": email, "name": name, "facts": facts}
    return sorted(members.values(), key=lambda member: member["email"])


def read_emailed(path: Path | None) -> dict[str, datetime]:
    if path is None:
        return {}
    emailed: dict[str, datetime] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        email, when = (part.strip() for part in line.split(",", 1))
        stamp = _time(when)
        if stamp is None:
            raise ValueError("Each emailed-by-hand line needs an ISO time.")
        emailed[normal_email(email)] = datetime.fromisoformat(stamp)
    return emailed


async def _approver(db: AsyncSession, operations_tenant_id: UUID) -> Person:
    approver = await db.scalar(select(Person).where(func.lower(Person.email) == APPROVER))
    member = await db.get(Membership, (operations_tenant_id, approver.id)) if approver else None
    if (
        approver is None
        or approver.email_verified_at is None
        or member is None
        or member.status != "active"
        or member.role not in {"admin", "owner"}
    ):
        raise ValueError(
            f"Verified approver {APPROVER} with an active admin/owner membership in the AC "
            "operations workspace is required."
        )
    return approver


async def change(
    db: AsyncSession,
    *,
    members: list[dict[str, Any]],
    emailed: dict[str, datetime],
    operations_tenant_id: UUID,
    issue: str,
    apply: bool,
) -> dict[str, Any]:
    now, run_id = datetime.now(UTC), uuid4()
    approver = await _approver(db, operations_tenant_id)
    known = set((await db.scalars(select(SalesXrayTesterEvent.email).distinct())).all())
    new = [member for member in members if member["email"] not in known]
    unknown_emailed = sorted(set(emailed) - {member["email"] for member in members})
    if unknown_emailed:
        raise ValueError(f"{len(unknown_emailed)} emailed-by-hand address(es) are not members.")
    result: dict[str, Any] = {
        "run_id": str(run_id),
        "issue": issue,
        "approver_email": APPROVER,
        "before": {"testers": len(known)},
        "after": {"testers": len(known) + len(new)},
        "adding": len(new),
        "already_listed": len(members) - len(new),
        "emailed_by_hand": sum(1 for member in new if member["email"] in emailed),
        "with_app_sessions": sum(1 for member in new if member["facts"]["app_sessions"]),
        "applied": False,
    }
    if not apply or not new:
        return result
    for index, member in enumerate(new):
        # Microseconds apart so each member's rows keep their order.
        at = now.replace(microsecond=0)
        rows = [
            SalesXrayTesterEvent(
                id=uuid4(),
                email=member["email"],
                kind="listed",
                actor_person_id=approver.id,
                name=member["name"],
                note=f"In the Play group when the list began ({issue})",
                facts=member["facts"],
                created_at=at.replace(microsecond=index * 3),
            ),
            SalesXrayTesterEvent(
                id=uuid4(),
                email=member["email"],
                kind="added_to_group",
                via="seed",
                actor_person_id=approver.id,
                created_at=at.replace(microsecond=index * 3 + 1),
            ),
        ]
        if member["email"] in emailed:
            rows.append(
                SalesXrayTesterEvent(
                    id=uuid4(),
                    email=member["email"],
                    kind="emailed",
                    via="gmail",
                    actor_person_id=approver.id,
                    created_at=emailed[member["email"]],
                )
            )
        db.add_all(rows)
    await db.flush()
    await AuditRepository(db).append(
        tenant_id=operations_tenant_id,
        actor_person_id=approver.id,
        action="sales_xray.testers_seed_data_change",
        resource_type="sales_xray_tester_list",
        resource_id=run_id,
        payload={
            "run_id": str(run_id),
            "issue": issue,
            "approver_email": APPROVER,
            "before": result["before"],
            "after": result["after"],
            "adding": len(new),
        },
        reason="Owner order 13 Nov 2026: seed the tester list with the Play group's members",
        now=now,
    )
    result["applied"] = True
    return result


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    settings = Settings()
    if settings.environment != args.environment or settings.operations_tenant_id is None:
        raise ValueError("Select the exact runtime environment and AC operations workspace.")
    members = read_members(Path(args.members))
    emailed = read_emailed(Path(args.emailed_by_hand) if args.emailed_by_hand else None)
    engine = create_async_engine(settings.database_url, echo=False, hide_parameters=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db, db.begin():
            result = await change(
                db,
                members=members,
                emailed=emailed,
                operations_tenant_id=settings.operations_tenant_id,
                issue=args.issue,
                apply=args.apply,
            )
            result["environment"] = settings.environment
            return result
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--environment", choices=("development", "staging", "production"), required=True
    )
    parser.add_argument("--members", required=True, help="CSV of the group's members (not in git)")
    parser.add_argument("--emailed-by-hand", help="lines of 'email,ISO time'")
    parser.add_argument("--issue", required=True, help="the tracked issue or task reference")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(execute(args)), sort_keys=True))


if __name__ == "__main__":
    main()
