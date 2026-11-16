"""Move one person's open leads in one workspace to the no-owner pool (approved data change).

Owner, 17 Nov 2026 (Wise Life and iSolar, through the orchestrator): "Shivam is not going to
do any sales, so remove whatever leads are assigned to him and throw them into the no-owner
pool." The app's own hand-over path (``LeadDesk._set_owner``, as a manager's reassign writes
it), in one transaction:
  1. every open lead (not Won, Lost or Junk; not merged into another) the person owns in the
     workspace is left with no owner; its open tasks go with it, as on any hand-over;
  2. each lead's history gets one line, "Reassigned from <person> to nobody", with the
     reason given;
  3. nobody is told: a lead with no owner rings no bell and sends no phone alert, and the
     person's own "is your lead now" lines for these leads go quiet;
  4. one audit event naming the approver, the issue and the lead ids.
The person stays a member with the same role; only their leads move. Closed leads keep their
owner (who won or lost them stays true).

A dry run (the default) makes the whole change in its transaction, reports it and rolls it
back. ``--apply`` commits; a rerun moves nothing (each lead's line has its own command id).
``--read`` counts the person's open leads now.

Run inside the API container with the deployed settings (its filesystem is read-only, so the
input goes inline):
    docker exec -i <api> python - '<input JSON>' [--apply | --read] < leads-to-no-owner-pool.py
input: {"command_id", "tenant" (its id or first 8 characters), "person_id" (or
        "person_email"), "approver_email", "approver", "issue", "reason", "actor_email"?}
Prints counts and lead id prefixes only; never a lead's name, number or email.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from typing import Any, Final, Literal
from uuid import UUID, uuid5

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.settings import get_settings
from ac_platform.audit.service import append_audit_event
from ac_platform.identity.models import Person
from ac_platform.lead_desk.models import Lead
from ac_platform.lead_desk.store import LeadDesk, Viewer, person_name
from ac_platform.lead_desk.vocabulary import CLOSED_STAGES

Mode = Literal["dry-run", "apply", "read"]
ACTION: Final = "lead_desk.leads_to_pool_data_change"


def _input(path: str) -> dict[str, Any]:
    if path.lstrip().startswith("{"):
        return dict(json.loads(path))
    with open(path, encoding="utf-8") as file:
        return dict(json.load(file))


async def _tenant(db: AsyncSession, given: str) -> UUID:
    given = given.strip().lower()
    if len(given) == 36:
        return UUID(given)
    found = (
        (
            await db.execute(
                text("select id from tenants where cast(id as text) like :p order by id limit 2"),
                {"p": f"{given}%"},
            )
        )
        .scalars()
        .all()
    )
    if len(given) < 8 or len(found) != 1:
        raise SystemExit(json.dumps({"refused": "tenant_not_found_once"}))
    return UUID(str(found[0]))


async def _person(
    db: AsyncSession, *, email: str | None = None, person_id: str | None = None
) -> Person | None:
    if person_id:
        return await db.get(Person, UUID(person_id))
    if not email:
        return None
    found: Person | None = await db.scalar(
        select(Person).where(func.lower(Person.email) == email.strip().lower())
    )
    return found


async def _open(db: AsyncSession, tenant_id: UUID, person_id: UUID) -> list[Lead]:
    return list(
        (
            await db.scalars(
                select(Lead)
                .where(
                    Lead.tenant_id == tenant_id,
                    Lead.owner_person_id == person_id,
                    Lead.merged_into_id.is_(None),
                    Lead.stage.not_in(CLOSED_STAGES),
                )
                .order_by(Lead.created_at, Lead.id)
                .with_for_update()
            )
        ).all()
    )


async def run(
    db: AsyncSession, spec: dict[str, Any], *, mode: Mode, now: datetime
) -> dict[str, Any]:
    command_id = UUID(spec["command_id"])
    if mode == "read":
        await db.execute(text("SET TRANSACTION READ ONLY"))
    tenant_id = await _tenant(db, str(spec["tenant"]))
    person = await _person(db, email=spec.get("person_email"), person_id=spec.get("person_id"))
    if person is None:
        raise SystemExit(json.dumps({"refused": "person_not_found"}))
    report: dict[str, Any] = {
        "mode": mode,
        "tenant_id": str(tenant_id),
        "person": str(person.id)[:8],
    }
    if mode == "read":
        leads = (
            await db.execute(
                select(Lead.stage, Lead.pipeline).where(
                    Lead.tenant_id == tenant_id,
                    Lead.owner_person_id == person.id,
                    Lead.merged_into_id.is_(None),
                )
            )
        ).all()
        report["status"] = "read"
        report["owned"] = dict(Counter(f"{side or 'live'}:{stage}" for stage, side in leads))
        return report
    approver = await _person(db, email=str(spec["approver_email"]))
    actor = await _person(db, email=str(spec.get("actor_email") or spec["approver_email"]))
    if approver is None or actor is None:
        raise SystemExit(json.dumps({"refused": "approver_not_found", **report}))
    reason = str(spec.get("reason") or "Moved to the no-owner pool (data change)")[:300]
    desk = LeadDesk(
        db,
        Viewer(
            person_id=actor.id,
            tenant_id=tenant_id,
            role="owner",
            name=person_name(actor) if actor.id != approver.id else "Data change",
        ),
        now=now,
    )
    leads = await _open(db, tenant_id, person.id)
    report["before"] = {"open": len(leads), "by_stage": dict(Counter(lead.stage for lead in leads))}
    moved: list[str] = []
    counts: Counter[str] = Counter()
    for lead in leads:
        step = uuid5(command_id, str(lead.id))
        if await desk._command_seen(step) is not None:
            counts["done_before"] += 1
            continue
        await desk._set_owner(
            lead, None, reason, "manual", actor=actor.id, kind="reassigned", command_id=step
        )
        moved.append(str(lead.id))
        counts["moved"] += 1
    await db.flush()
    report["counts"] = dict(counts)
    report["moved"] = [lead_id[:8] for lead_id in moved]
    report["audited"] = bool(moved)
    if moved:
        await append_audit_event(
            db,
            tenant_id=tenant_id,
            actor_person_id=approver.id,
            actor_type="operator",
            action=ACTION,
            resource_type="tenant",
            resource_id=tenant_id,
            request_id=str(uuid5(command_id, "audit")),
            reason="Owner request: a person's open leads go to the no-owner pool",
            payload={
                "issue": spec.get("issue"),
                "command_id": str(command_id),
                "person_id": str(person.id),
                "approver": spec.get("approver"),
                "lead_ids": moved,
                "counts": dict(counts),
            },
        )
    report["after"] = {"open": len(await _open(db, tenant_id, person.id))}
    report["status"] = "applied" if mode == "apply" else "rehearsed_and_rolled_back"
    return report


async def execute(
    sessions: async_sessionmaker[AsyncSession], spec: dict[str, Any], *, mode: Mode, now: datetime
) -> dict[str, Any]:
    async with sessions() as db:
        try:
            report = await run(db, spec, mode=mode, now=now)
        except BaseException:
            await db.rollback()
            raise
        if mode == "apply":
            await db.commit()
        else:
            await db.rollback()
    return report


async def main(path: str, mode: Mode) -> int:
    engine = create_async_engine(get_settings().database_url)
    try:
        report = await execute(
            async_sessionmaker(engine, expire_on_commit=False),
            _input(path),
            mode=mode,
            now=datetime.now(UTC),
        )
    finally:
        await engine.dispose()
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    chosen: Mode = "apply" if "--apply" in flags else "read" if "--read" in flags else "dry-run"
    raise SystemExit(asyncio.run(main(args[0], chosen)))
