"""Rewind one workspace's ad-platform collector to a given time (approved data change).

Found 16 Nov 2026 (Wise Life): the stage sender skipped every stage move, because each move
names the lead's own pipeline and the collector took that for a move between pipelines. The
fix (``engine.between_pipelines``) sends moves from its release on; the moves made before it
were read and passed by. This sets the workspace's collector cursor (``lead_desk_settings``
config ``ad_sync.cursor``) back to ``rewind_to``, so the running sender reads those moves
again on its next minute and freezes the events they reach. Nothing else changes.

Safe to read again: each lead, platform, destination and event name is one row of
``lead_desk_conversions`` (unique; a second match does nothing), and Meta's ``event_id`` is the
same for the same lead and name, so an event already sent (every "Lead") is never sent twice.
Events older than the platforms' window (7 days, less 10 minutes) are never read, so a
``rewind_to`` older than that is refused.

In one transaction:
  1. the workspace's Lead Desk settings row, locked; refused unless a platform is on;
  2. a preview: the deployed collector run over the rewound cursor in a savepoint that is
     rolled back, counting the events it would freeze by platform, event name, stage and the
     kind of history line (counts only);
  3. the cursor set to ``rewind_to``;
  4. one audit event naming the approver, the issue, the cursor before and after and the
     preview's counts.
A dry run (the default) does all of it and rolls back. ``--apply`` commits. A rerun of the
same ``command_id`` changes nothing. Refused on an engine without the stage-move fix.

Run inside the API container with the deployed settings (its filesystem is read-only, so the
input goes inline):
    docker exec -i <api> python - '<input JSON>' [--apply] < ad-sync-rewind.py
input: {"command_id", "tenant" (its id or first 8 characters), "rewind_to" (ISO time with a
        zone), "approver_email", "approver", "issue", "reason"?}
Prints counts only; never a lead's name, number or email.
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
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import append_audit_event
from ac_platform.identity.models import Person
from ac_platform.lead_desk.journey import engine, mapping
from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.models import LeadConversion, LeadDeskSettings, LeadEvent

Mode = Literal["dry-run", "apply"]
ACTION: Final = "lead_desk.ad_sync_rewind_data_change"
ZERO: Final = UUID(int=0)


def _input(path: str) -> dict[str, Any]:
    if path.lstrip().startswith("{"):
        return dict(json.loads(path))
    with open(path, encoding="utf-8") as file:
        return dict(json.load(file))


def _refuse(reason: str, **report: Any) -> SystemExit:
    return SystemExit(json.dumps({"refused": reason, **report}))


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
        raise _refuse("tenant_not_found_once")
    return UUID(str(found[0]))


def _cursor(config: dict[str, Any]) -> str | None:
    at = mapping.cursor(config)
    return at[0].isoformat() if at else None


async def _preview(
    db: AsyncSession,
    tenant_id: UUID,
    config: dict[str, Any],
    *,
    environment: str,
    now: datetime,
) -> dict[str, Any]:
    """What the deployed collector would freeze from the rewound cursor; rolled back."""
    by_name: Counter[str] = Counter()
    by_stage: Counter[str] = Counter()
    by_line: Counter[str] = Counter()
    read = 0
    savepoint = await db.begin_nested()
    try:
        journey = await journeys.read(db, tenant_id)
        current = await engine.adopt_meta(db, tenant_id, dict(config), now)
        started = now
        while True:
            before = mapping.cursor(current)
            _, current = await engine._collect_one(
                db, tenant_id, current, journey, environment=environment, now=now
            )
            if mapping.cursor(current) == before:
                break
            read += 1
        made = (
            await db.execute(
                select(LeadConversion.provider, LeadConversion.event_name, LeadConversion.stage_key)
                .add_columns(LeadEvent.kind)
                .join(LeadEvent, LeadEvent.id == LeadConversion.source_event_id)
                .where(LeadConversion.tenant_id == tenant_id, LeadConversion.created_at == started)
            )
        ).all()
        for provider, name, stage, kind in made:
            by_name[f"{provider}:{name}"] += 1
            by_stage[str(stage)] += 1
            by_line[str(kind)] += 1
    finally:
        await savepoint.rollback()
    return {
        "would_freeze": sum(by_name.values()),
        "by_event_name": dict(sorted(by_name.items())),
        "by_stage": dict(sorted(by_stage.items())),
        "by_history_line": dict(sorted(by_line.items())),
        "collector_passes": read,
    }


async def run(
    db: AsyncSession, spec: dict[str, Any], *, mode: Mode, environment: str, now: datetime
) -> dict[str, Any]:
    command_id = UUID(spec["command_id"])
    tenant_id = await _tenant(db, str(spec["tenant"]))
    rewind_to = datetime.fromisoformat(str(spec["rewind_to"]))
    report: dict[str, Any] = {
        "mode": mode,
        "tenant_id": str(tenant_id),
        "rewind_to": rewind_to.isoformat() if rewind_to.tzinfo else None,
    }
    if rewind_to.tzinfo is None:
        raise _refuse("rewind_to_needs_a_zone", **report)
    if not hasattr(engine, "between_pipelines"):
        raise _refuse("engine_without_the_stage_move_fix", **report)
    if rewind_to < now - engine.MAX_AGE:
        raise _refuse("rewind_to_older_than_the_platform_window", **report)
    if rewind_to > now:
        raise _refuse("rewind_to_in_the_future", **report)
    request_id = str(uuid5(command_id, "audit"))
    done = await db.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.action == ACTION,
            AuditEvent.request_id == request_id,
        )
    )
    if done:
        report["status"] = "done_before"
        return report
    approver = await db.scalar(
        select(Person).where(func.lower(Person.email) == str(spec["approver_email"]).lower())
    )
    if approver is None:
        raise _refuse("approver_not_found", **report)
    row = await db.scalar(
        select(LeadDeskSettings).where(LeadDeskSettings.tenant_id == tenant_id).with_for_update()
    )
    config = dict(row.config or {}) if row is not None else {}
    if row is None or not mapping.any_on(config):
        raise _refuse("no_ad_platform_on", **report)
    report["platforms_on"] = [p for p in mapping.available() if mapping.read(config, p).ready]
    report["cursor_before"] = _cursor(config)
    rewound = mapping.with_cursor(config, rewind_to, ZERO)
    report["preview"] = await _preview(db, tenant_id, rewound, environment=environment, now=now)
    row.config = rewound
    await db.flush()
    report["cursor_after"] = _cursor(rewound)
    await append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_person_id=approver.id,
        actor_type="operator",
        action=ACTION,
        resource_type="tenant",
        resource_id=tenant_id,
        request_id=request_id,
        reason=str(
            spec.get("reason") or "Owner request: send the stage moves the sender passed by"
        )[:300],
        payload={
            "issue": spec.get("issue"),
            "command_id": str(command_id),
            "approver": spec.get("approver"),
            "cursor_before": report["cursor_before"],
            "cursor_after": report["cursor_after"],
            "preview": report["preview"],
        },
    )
    report["audited"] = True
    report["status"] = "applied" if mode == "apply" else "rehearsed_and_rolled_back"
    return report


async def execute(
    sessions: async_sessionmaker[AsyncSession],
    spec: dict[str, Any],
    *,
    mode: Mode,
    environment: str,
    now: datetime,
) -> dict[str, Any]:
    async with sessions() as db:
        try:
            report = await run(db, spec, mode=mode, environment=environment, now=now)
        except BaseException:
            await db.rollback()
            raise
        if mode == "apply":
            await db.commit()
        else:
            await db.rollback()
    return report


async def main(path: str, mode: Mode) -> int:
    settings = get_settings()
    engine_ = create_async_engine(settings.database_url)
    try:
        report = await execute(
            async_sessionmaker(engine_, expire_on_commit=False),
            _input(path),
            mode=mode,
            environment=settings.environment,
            now=datetime.now(UTC),
        )
    finally:
        await engine_.dispose()
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    chosen: Mode = "apply" if "--apply" in flags else "dry-run"
    raise SystemExit(asyncio.run(main(args[0], chosen)))
