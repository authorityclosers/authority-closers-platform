"""Mark named leads as test data, reversibly (approved data change).

Owner, 17 Nov 2026 review: "test leads pollute karuu naye data ... data clean disaayalaa
paahije". QA phones and test-call runs had used a real seller's sign-in, so their leads and
calls filled her seller bar. Marked leads stay in every list (the Leads "Test data" filter finds
them) and leave every number (LeadDesk._counted_leads). Nothing is deleted.

Sets only ``test_data = true`` on the exact lead ids given, in one organisation. Nothing else on
a lead changes: not its stage, owner, revision or updated_at, and no event is written to it.
In one transaction:
  1. the leads are locked; every id must be found in the organisation and their number must
     equal ``expected``;
  2. the ids already marked are left as they are; the others are marked;
  3. one audit event names the approver, the issue and the ids this run changed, so ``--undo``
     can put back exactly those.

A dry run (the default) makes the change in its transaction, reports it and rolls it back.
``--apply`` commits; a rerun changes nothing and writes no audit event. ``--read`` reads the
flags back. ``--undo`` (with ``--apply`` to commit) clears the flag on the ids the original run
(same ``command_id``) changed, and only on those still marked; one audit event.

Run inside the API container with the deployed settings (its filesystem is read-only, so the
input goes inline):
    docker exec -i <api> python - '<input JSON>' [--apply] [--read] [--undo] < flag-test-leads.py
input: {"command_id", "tenant", "lead_ids", "expected", "approver_email", "approver", "issue"}
Prints ids and counts only; never a lead's name, number or email.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Final, Literal
from uuid import UUID, uuid5

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.settings import get_settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import append_audit_event
from ac_platform.identity.models import Person
from ac_platform.lead_desk.models import Lead

Mode = Literal["dry-run", "apply", "read"]
ACTION: Final = "lead_desk.test_data_flag_data_change"
UNDO_ACTION: Final = "lead_desk.test_data_flag_undo_data_change"
FIELDS: Final = frozenset(
    {"command_id", "tenant", "lead_ids", "expected", "approver_email", "approver", "issue"}
)
MOST: Final = 500


def refuse(reason: str, **facts: Any) -> SystemExit:
    return SystemExit(json.dumps({"refused": reason, **facts}))


def spec_of(raw: str) -> dict[str, Any]:
    spec = dict(json.loads(raw))
    missing = FIELDS - set(spec)
    if missing:
        raise refuse("missing_input", fields=sorted(missing))
    UUID(str(spec["command_id"]))
    UUID(str(spec["tenant"]))
    ids = [str(UUID(str(lead))) for lead in spec["lead_ids"]]
    if not ids or len(ids) > MOST:
        raise refuse("lead_ids_must_be_1_to_500")
    if len(set(ids)) != len(ids):
        raise refuse("lead_ids_repeat")
    if int(spec["expected"]) != len(ids):
        raise refuse("count_mismatch", given=len(ids), expected=int(spec["expected"]))
    if not str(spec["approver"]).strip() or not str(spec["issue"]).strip():
        raise refuse("approver_and_issue_required")
    return {**spec, "lead_ids": ids}


def short(ids: list[UUID]) -> list[str]:
    return sorted(str(lead)[:8] for lead in ids)


async def flags(db: AsyncSession, tenant: UUID, ids: list[UUID], *, lock: bool) -> dict[UUID, bool]:
    query = select(Lead.id, Lead.test_data).where(Lead.tenant_id == tenant, Lead.id.in_(ids))
    if lock:
        query = query.with_for_update()
    return {row.id: bool(row.test_data) for row in (await db.execute(query)).all()}


async def counted(db: AsyncSession, tenant: UUID) -> dict[str, int]:
    rows = (
        await db.execute(
            select(Lead.test_data, func.count())
            .where(Lead.tenant_id == tenant)
            .group_by(Lead.test_data)
        )
    ).all()
    found = {bool(flag): int(count) for flag, count in rows}
    return {"test": found.get(True, 0), "real": found.get(False, 0)}


async def first_run(db: AsyncSession, tenant: UUID, command_id: UUID) -> list[UUID]:
    """The ids the original run with this command id changed (from its audit event)."""
    payloads = (
        await db.scalars(
            select(AuditEvent.payload).where(
                AuditEvent.tenant_id == tenant,
                AuditEvent.action == ACTION,
                AuditEvent.request_id == str(uuid5(command_id, "audit")),
            )
        )
    ).all()
    if len(payloads) != 1:
        raise refuse("original_run_not_found", found=len(payloads))
    return [UUID(str(lead)) for lead in dict(payloads[0])["changed_ids"]]


async def run(db: AsyncSession, spec: dict[str, Any], *, mode: Mode, undo: bool) -> dict[str, Any]:
    tenant = UUID(str(spec["tenant"]))
    command_id = UUID(str(spec["command_id"]))
    ids = [UUID(lead) for lead in spec["lead_ids"]]
    if mode == "read":
        await db.execute(text("SET TRANSACTION READ ONLY"))
        now = await flags(db, tenant, ids, lock=False)
        return {
            "mode": mode,
            "undo": undo,
            "tenant": str(tenant)[:8],
            "found": len(now),
            "marked": short([lead for lead, flag in now.items() if flag]),
            "unmarked": short([lead for lead, flag in now.items() if not flag]),
            "organisation": await counted(db, tenant),
            "status": "read",
        }
    email = str(spec["approver_email"]).lower()
    operator = await db.scalar(select(Person).where(func.lower(Person.email) == email))
    if operator is None:
        raise refuse("approver_not_found")
    before = await counted(db, tenant)
    now = await flags(db, tenant, ids, lock=True)
    if len(now) != len(ids):
        raise refuse("lead_not_in_organisation", missing=short([i for i in ids if i not in now]))
    if undo:
        wanted = [lead for lead in await first_run(db, tenant, command_id) if now.get(lead)]
        value, action, request = False, UNDO_ACTION, str(uuid5(command_id, "undo"))
    else:
        wanted = [lead for lead in ids if not now[lead]]
        value, action, request = True, ACTION, str(uuid5(command_id, "audit"))
    if wanted:
        # Only the flag: no revision, updated_at or event, so no list re-sorts.
        await db.execute(
            update(Lead)
            .where(Lead.tenant_id == tenant, Lead.id.in_(wanted))
            .values(test_data=value)
            .execution_options(synchronize_session=False)
        )
    after = await counted(db, tenant)
    if after["test"] + after["real"] != before["test"] + before["real"]:
        raise refuse("lead_count_changed", before=before, after=after)
    report: dict[str, Any] = {
        "mode": mode,
        "undo": undo,
        "tenant": str(tenant)[:8],
        "given": len(ids),
        "already": len(ids) - len(wanted) if not undo else None,
        "changed": len(wanted),
        "changed_ids": short(wanted),
        "before": before,
        "after": after,
    }
    if wanted:
        await append_audit_event(
            db,
            tenant_id=tenant,
            actor_person_id=operator.id,
            actor_type="operator",
            action=action,
            resource_type="tenant",
            resource_id=tenant,
            request_id=request,
            reason=(
                f"Approved by {spec['approver']}: "
                + ("unmark leads marked as test data" if undo else "mark leads as test data")
            ),
            payload={
                "issue": spec["issue"],
                "approver": spec["approver"],
                "command_id": str(command_id),
                "changed_ids": [str(lead) for lead in wanted],
                "before": before,
                "after": after,
            },
        )
    report["status"] = "applied" if mode == "apply" else "rehearsed_and_rolled_back"
    return report


async def execute(
    sessions: async_sessionmaker[AsyncSession],
    spec: dict[str, Any],
    *,
    mode: Mode,
    undo: bool = False,
) -> dict[str, Any]:
    async with sessions() as db:
        try:
            report = await run(db, spec, mode=mode, undo=undo)
        except BaseException:
            await db.rollback()
            raise
        if mode == "apply":
            await db.commit()
        else:
            await db.rollback()
    return report


async def main(raw: str, mode: Mode, undo: bool) -> int:
    engine = create_async_engine(get_settings().database_url)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        report = await execute(sessions, spec_of(raw), mode=mode, undo=undo)
    finally:
        await engine.dispose()
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    switches = {a for a in sys.argv[1:] if a.startswith("--")}
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    chosen: Mode = (
        "apply" if "--apply" in switches else "read" if "--read" in switches else "dry-run"
    )
    raise SystemExit(asyncio.run(main(args[0], chosen, "--undo" in switches)))
