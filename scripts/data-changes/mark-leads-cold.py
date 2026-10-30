"""Mark one bulk-uploaded file's leads cold (approved data change).

Owner, 30 Oct 2026, urgent fix 6: "Mark the existing ~350 bulk-uploaded leads in the Authority
Closers org as cold". Needs migration 0146 (``lead_desk_leads.pipeline``).

Sets only ``pipeline = 'cold'`` on one organisation's leads whose source is "csv" and whose
label starts with the given file label. Nothing else on a lead changes: not its stage, owner,
revision or updated_at, so no list re-sorts and nothing is re-staged (the owner's ground rule).
In one transaction:
  1. the matching leads are locked; their number must equal ``expected`` (or, on a rerun, they
     are all cold already and nothing changes);
  2. counts by stage and by live/cold are taken before and after; the stage counts must be
     identical, or the change is refused;
  3. one audit event names the approver and the issue.

A dry run (the default) makes the change in its transaction, reports it and rolls it back.
``--apply`` commits; a rerun changes nothing. ``--read`` reads the counts back.

Run inside the API container with the deployed settings (its filesystem is read-only, so the
input goes inline):
    docker exec -i <api> python - '<input JSON>' [--apply | --read] < mark-leads-cold.py
input: {"command_id", "tenant" (the organisation's id), "label_prefix", "expected",
        "approver_email", "issue"}
Prints counts only; never a lead's name, number or email.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Iterable
from typing import Any, Final, Literal
from uuid import UUID, uuid5

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.settings import get_settings
from ac_platform.audit.service import append_audit_event
from ac_platform.identity.models import Person

Mode = Literal["dry-run", "apply", "read"]
ACTION: Final = "lead_desk.pipeline_cold_data_change"
FIELDS: Final = frozenset(
    {"command_id", "tenant", "label_prefix", "expected", "approver_email", "issue"}
)

HAS_COLUMN = text(
    "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' "
    "AND table_name = 'lead_desk_leads' AND column_name = 'pipeline')"
)
COUNTS = text(
    "SELECT 'stage' AS k, stage AS v, count(*) AS n FROM lead_desk_leads "
    "WHERE tenant_id = :tenant GROUP BY stage "
    "UNION ALL "
    "SELECT 'pipeline', coalesce(pipeline, 'live'), count(*) FROM lead_desk_leads "
    "WHERE tenant_id = :tenant GROUP BY coalesce(pipeline, 'live')"
)
LOCK = text(
    "SELECT pipeline IS NOT DISTINCT FROM 'cold' AS cold FROM lead_desk_leads "
    "WHERE tenant_id = :tenant AND source = 'csv' "
    "AND left(source_label, length(:label)) = :label FOR UPDATE"
)
MARK = text(
    "UPDATE lead_desk_leads SET pipeline = 'cold' "
    "WHERE tenant_id = :tenant AND source = 'csv' "
    "AND left(source_label, length(:label)) = :label "
    "AND pipeline IS DISTINCT FROM 'cold' RETURNING id"
)


def refuse(reason: str, **facts: Any) -> SystemExit:
    return SystemExit(json.dumps({"refused": reason, **facts}))


def spec_of(raw: str) -> dict[str, Any]:
    spec = dict(json.loads(raw))
    missing = FIELDS - set(spec)
    if missing:
        raise refuse("missing_input", fields=sorted(missing))
    UUID(str(spec["command_id"]))
    UUID(str(spec["tenant"]))
    # "File: " is every uploaded file (owner, 30 Oct 2026: all uploads cold, not Meta's leads).
    if len(str(spec["label_prefix"]).strip()) < 5:
        raise refuse("label_prefix_too_short")
    if int(spec["expected"]) < 1:
        raise refuse("expected_must_be_positive")
    return spec


def decide(matched: int, already_cold: int, expected: int) -> str:
    """What a run does: "mark" the file's live leads, "rerun" when they are all cold already,
    or refuse when the file's lead count is not the one the owner approved."""
    if matched != expected:
        raise refuse("count_mismatch", matched=matched, expected=expected)
    return "rerun" if already_cold == matched else "mark"


def tally(rows: Iterable[Any]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {"stage": {}, "pipeline": {}}
    for kind, value, count in rows:
        out[str(kind)][str(value)] = int(count)
    return out


async def run(db: AsyncSession, spec: dict[str, Any], *, mode: Mode) -> dict[str, Any]:
    tenant = UUID(str(spec["tenant"]))
    params = {"tenant": tenant, "label": str(spec["label_prefix"])}
    if mode == "read":
        await db.execute(text("SET TRANSACTION READ ONLY"))
    if not await db.scalar(HAS_COLUMN):
        raise refuse("migration_0146_not_applied")
    before = tally((await db.execute(COUNTS, {"tenant": tenant})).all())
    report: dict[str, Any] = {"mode": mode, "tenant": str(tenant)[:8], "before": before}
    if mode == "read":
        report["status"] = "read"
        return report
    email = str(spec["approver_email"]).lower()
    approver = await db.scalar(select(Person).where(func.lower(Person.email) == email))
    if approver is None:
        raise refuse("approver_not_found")
    flags = [bool(row.cold) for row in (await db.execute(LOCK, params)).all()]
    action = decide(len(flags), sum(flags), int(spec["expected"]))
    changed = len((await db.execute(MARK, params)).all()) if action == "mark" else 0
    after = tally((await db.execute(COUNTS, {"tenant": tenant})).all())
    if after["stage"] != before["stage"]:
        raise refuse("stage_counts_changed", before=before, after=after)
    report.update(
        {"matched": len(flags), "already_cold": sum(flags), "changed": changed, "after": after}
    )
    if changed:
        command_id = UUID(str(spec["command_id"]))
        await append_audit_event(
            db,
            tenant_id=tenant,
            actor_person_id=approver.id,
            actor_type="operator",
            action=ACTION,
            resource_type="tenant",
            resource_id=tenant,
            request_id=str(uuid5(command_id, "audit")),
            reason="Owner request: mark a bulk-uploaded file's leads cold",
            payload={
                "issue": spec["issue"],
                "command_id": str(command_id),
                "label_prefix": params["label"],
                "changed": changed,
                "before": before,
                "after": after,
            },
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
