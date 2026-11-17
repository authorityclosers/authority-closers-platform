"""Give Meta leads filed before 26 Oct 2026 the time Meta made them (approved data change).

Shivam's review of the lead page with the owner, 17 Nov 2026: a Meta lead shows "Meta ad ·
16 Nov, 10:42" at the top, Meta's own time, and the time it reached Sales X-Ray isn't shown to
sellers in a way that contradicts it. Since 26 Oct 2026 (1109543ad) every Meta lead is filed
with ``received_at`` = Meta's ``created_time``; leads filed before then have none, so their page
and the Leads list fell back to when Sales X-Ray filed them (on dev, 3 to 41 days later). Each
kept Meta's time in its own record (``payload.meta.created_time``), and this copies it over.

Sets only ``received_at``, to Meta's time or the filing time when that is earlier (as the intake
does), on Meta leads that have none and whose record holds a readable Meta time. Nothing else
changes: not the stage, owner, revision or updated_at. In one transaction:
  1. the matching leads are locked; their number must equal ``expected`` (or, on a rerun, there
     are none left and nothing changes);
  2. one audit event per organisation names the approver and the issue.

A dry run (the default) makes the change in its transaction, reports it and rolls it back.
``--apply`` commits; a rerun changes nothing. ``--read`` counts what is left, read-only.

Run inside the API container with the deployed settings (its filesystem is read-only, so the
input goes inline):
    docker exec -i <api> python - '<input JSON>' [--apply | --read] < backfill-meta-received-at.py
input: {"command_id", "expected", "approver_email", "issue"} and optionally "tenant" (one
organisation's id; without it, every organisation).
Prints counts only; never a lead's name, number or email.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Final, Literal
from uuid import UUID, uuid5

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.settings import get_settings
from ac_platform.audit.service import append_audit_event
from ac_platform.identity.models import Person

Mode = Literal["dry-run", "apply", "read"]
ACTION: Final = "lead_desk.meta_received_at_data_change"
FIELDS: Final = frozenset({"command_id", "expected", "approver_email", "issue"})

# Meta's created_time, as its Graph API writes it (2026-09-01T10:00:00+0000), read from the
# lead's own record; the same conditions in each statement, written out whole.
LEFT = text(
    "SELECT tenant_id, count(*) AS n FROM lead_desk_leads "
    "WHERE source = 'meta' AND received_at IS NULL "
    "AND (payload::jsonb #>> '{meta,created_time}') "
    "~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}' "
    "AND (CAST(:tenant AS uuid) IS NULL OR tenant_id = CAST(:tenant AS uuid)) "
    "GROUP BY tenant_id"
)
LOCK = text(
    "SELECT id FROM lead_desk_leads "
    "WHERE source = 'meta' AND received_at IS NULL "
    "AND (payload::jsonb #>> '{meta,created_time}') "
    "~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}' "
    "AND (CAST(:tenant AS uuid) IS NULL OR tenant_id = CAST(:tenant AS uuid)) "
    "FOR UPDATE"
)
FILL = text(
    "UPDATE lead_desk_leads "
    "SET received_at = least((payload::jsonb #>> '{meta,created_time}')::timestamptz, created_at) "
    "WHERE source = 'meta' AND received_at IS NULL "
    "AND (payload::jsonb #>> '{meta,created_time}') "
    "~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}' "
    "AND (CAST(:tenant AS uuid) IS NULL OR tenant_id = CAST(:tenant AS uuid)) "
    "RETURNING tenant_id"
)


def refuse(reason: str, **facts: Any) -> SystemExit:
    return SystemExit(json.dumps({"refused": reason, **facts}))


def spec_of(raw: str) -> dict[str, Any]:
    spec = dict(json.loads(raw))
    missing = FIELDS - set(spec)
    if missing:
        raise refuse("missing_input", fields=sorted(missing))
    UUID(str(spec["command_id"]))
    if spec.get("tenant") is not None:
        UUID(str(spec["tenant"]))
    if int(spec["expected"]) < 0:
        raise refuse("expected_must_not_be_negative")
    return spec


def decide(matched: int, expected: int) -> str:
    """What a run does: "fill" the leads still without Meta's time, "rerun" when none are left,
    or refuse when their number is not the one approved after the dry run."""
    if matched == 0:
        return "rerun"
    if matched != expected:
        raise refuse("count_mismatch", matched=matched, expected=expected)
    return "fill"


def per_tenant(rows: list[Any]) -> dict[str, int]:
    """Counts by organisation, its id cut to 8 characters (enough to tell them apart)."""
    return {str(tenant)[:8]: int(count) for tenant, count in rows}


async def run(db: AsyncSession, spec: dict[str, Any], *, mode: Mode) -> dict[str, Any]:
    params = {"tenant": str(spec["tenant"]) if spec.get("tenant") else None}
    if mode == "read":
        await db.execute(text("SET TRANSACTION READ ONLY"))
    before = (await db.execute(LEFT, params)).all()
    report: dict[str, Any] = {"mode": mode, "left_before": per_tenant(before)}
    if mode == "read":
        report["status"] = "read"
        return report
    email = str(spec["approver_email"]).lower()
    approver = await db.scalar(select(Person).where(func.lower(Person.email) == email))
    if approver is None:
        raise refuse("approver_not_found")
    matched = len((await db.execute(LOCK, params)).all())
    action = decide(matched, int(spec["expected"]))
    filled = (
        [row.tenant_id for row in (await db.execute(FILL, params)).all()]
        if action == "fill"
        else []
    )
    after = (await db.execute(LEFT, params)).all()
    if after:
        raise refuse("leads_left", left=per_tenant(after))
    changed: dict[UUID, int] = {}
    for tenant in filled:
        changed[tenant] = changed.get(tenant, 0) + 1
    report.update({"matched": matched, "changed": per_tenant(list(changed.items()))})
    command_id = UUID(str(spec["command_id"]))
    for tenant, count in changed.items():
        await append_audit_event(
            db,
            tenant_id=tenant,
            actor_person_id=approver.id,
            actor_type="operator",
            action=ACTION,
            resource_type="tenant",
            resource_id=tenant,
            request_id=str(uuid5(command_id, f"audit:{tenant}")),
            reason="Meta leads filed before 26 Oct 2026 take Meta's own time",
            payload={"issue": spec["issue"], "command_id": str(command_id), "changed": count},
        )
    report["status"] = "applied" if mode == "apply" else "rehearsed_and_rolled_back"
    return report


async def execute(
    sessions: async_sessionmaker[AsyncSession], spec: dict[str, Any], *, mode: Mode
) -> dict[str, Any]:
    async with sessions() as db:
        try:
            report = await run(db, spec, mode=mode)
        except BaseException:
            await db.rollback()
            raise
        if mode == "apply":
            await db.commit()
        else:
            await db.rollback()
    return report


async def main(raw: str, mode: Mode) -> int:
    engine = create_async_engine(get_settings().database_url)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        report = await execute(sessions, spec_of(raw), mode=mode)
    finally:
        await engine.dispose()
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    chosen: Mode = "apply" if "--apply" in flags else "read" if "--read" in flags else "dry-run"
    raise SystemExit(asyncio.run(main(args[0], chosen)))
