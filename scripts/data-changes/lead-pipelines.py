"""Lay out an organisation's lead pipelines and move chosen leads into one (approved data change).

Owner decision, 22 Oct 2026 (Suyash Kulkarni, through the orchestrator chat): "Go with A for partner
leads plus B for enquiries as two pipelines". Pipelines are a product feature (Leads → Lead stages);
this script does, in one transaction and as the app itself would, what a manager would otherwise do
by hand for one organisation:
  1. renames the first pipeline ("main") and, when stages are given, saves them as its new list
     (a new version: earlier stages stay, archived, and leads keep their place);
  2. makes the other pipeline when it is missing: its name, the lead sources it takes, its stages;
  3. moves the leads picked (one source, file label starting with the text given) into it, each
     through the app's own move (``LeadDesk.move_pipeline``: one history event per lead, its owner,
     stage and follow-ups kept; it lands in the new pipeline's stage for its kind);
  4. writes one audit event naming the approver and the issue.
Nothing is deleted. Dry run unless --apply; a rerun after apply finds nothing to do.

Run inside the API container with the deployed settings (the rootfs is read-only, so pass the
input inline):
    docker exec -i <api> python - '<input JSON>' [--apply] < lead-pipelines.py
input: {"command_id", "tenant_id", "approver_email", "issue",
        "main": {"name", "stages": [{"key", "label", "milestone"}, ...] | null},
        "pipeline": {"key", "name", "sources": [...], "stages": [...]},
        "move": {"source": "csv", "label_prefix": "File: ..."}}
Prints counts, ids and stage names only; never a lead's name or number.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.settings import get_settings
from ac_platform.audit.service import append_audit_event
from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.journey import pipelines
from ac_platform.lead_desk.models import Lead
from ac_platform.lead_desk.store import LeadDesk, Viewer


def _input(path: str) -> dict[str, Any]:
    """The input, inline JSON or a file (the container's filesystem is read-only)."""
    if path.lstrip().startswith("{"):
        return dict(json.loads(path))
    with open(path, encoding="utf-8") as file:
        return dict(json.load(file))


def _shape(stages: Any) -> list[tuple[str, str, str, bool]]:
    return [(s.key, s.label, s.kind, s.archived) for s in stages]


async def _plan_stages(
    db: AsyncSession, tenant_id: UUID, key: str, wanted: list[dict[str, Any]] | None
) -> tuple[journeys.Journey, tuple[journeys.Stage, ...] | None]:
    """The pipeline's list now, and the list to save (None: nothing to change)."""
    before = await journeys.read(db, tenant_id, key)
    if not wanted:
        return before, None
    counts = await journeys.lead_counts(db, tenant_id, before)
    after = journeys.build(wanted, before, counts)
    return before, None if _shape(after) == _shape(before.stages) else after


async def main(path: str, apply: bool) -> int:
    spec = _input(path)
    command_id = UUID(spec["command_id"])
    tenant_id = UUID(spec["tenant_id"])
    target = spec["pipeline"]
    move = spec["move"]
    main_spec = spec.get("main") or {}
    engine = create_async_engine(get_settings().database_url)
    report: dict[str, Any] = {"mode": "apply" if apply else "dry-run", "tenant_id": str(tenant_id)}
    try:
        async with async_sessionmaker(engine)() as db, db.begin():
            approver = (
                await db.execute(
                    text("select id from persons where lower(email) = :e"),
                    {"e": spec["approver_email"].strip().lower()},
                )
            ).scalar_one()
            # One writer at a time for this organisation's pipelines.
            await db.execute(
                text("select id from tenants where id = :t for update"), {"t": tenant_id}
            )
            found = await pipelines.listed(db, tenant_id)
            main = pipelines.find(found, pipelines.MAIN)
            existing = next((item for item in found if item.key == target["key"]), None)
            main_before, main_after = await _plan_stages(
                db, tenant_id, pipelines.MAIN, main_spec.get("stages")
            )
            target_before, target_after = await _plan_stages(
                db, tenant_id, target["key"], target.get("stages")
            )
            leads = (
                await db.scalars(
                    select(Lead)
                    .where(
                        Lead.tenant_id == tenant_id,
                        Lead.source == move["source"],
                        Lead.source_label.startswith(move["label_prefix"]),
                        func.coalesce(Lead.pipeline_key, pipelines.MAIN) != target["key"],
                    )
                    .order_by(Lead.created_at, Lead.id)
                )
            ).all()
            landing = target_after or target_before.stages
            lands = journeys.Journey(1, None, tuple(landing), pipeline=target["key"])
            by_kind = Counter(lead.stage for lead in leads)
            # Where every lead lands, by the stage it shows now (owner's review, 22 Oct 2026):
            # the leads that move, by their main stage and their new pipeline's stage; the
            # leads that stay, by their main stage before and after the new list.
            moving = {lead.id for lead in leads}
            main_after_list = journeys.Journey(
                1, None, tuple(main_after or main_before.stages), pipeline=pipelines.MAIN
            )
            moves: Counter[tuple[str, str]] = Counter()
            for lead in leads:
                moves[
                    (
                        main_before.label(lead.stage, lead.step) or lead.stage,
                        (lands.resolve(lead.stage, None) or lands.stages[0]).label,
                    )
                ] += 1
            stays: Counter[tuple[str, str]] = Counter()
            for lead_id, kind, step in (
                await db.execute(
                    select(Lead.id, Lead.stage, Lead.step).where(
                        Lead.tenant_id == tenant_id, journeys.lead_in(pipelines.MAIN)
                    )
                )
            ).tuples():
                if lead_id in moving:
                    continue
                stays[
                    (
                        main_before.label(kind, step) or kind,
                        main_after_list.label(kind, step) or kind,
                    )
                ] += 1
            rename = bool(main_spec.get("name")) and main.name != main_spec["name"]
            report["before"] = {
                "pipelines": [
                    {"key": p.key, "name": p.name, "sources": list(p.sources)} for p in found
                ],
                "main_version": main_before.version,
                "main_stages": [s.label for s in main_before.live],
                "pipeline_version": target_before.version,
            }
            report["plan"] = {
                "rename_main": main_spec.get("name") if rename else None,
                "main_stages": [s.label for s in main_after if not s.archived]
                if main_after
                else None,
                "main_stages_archived": [s.label for s in main_after if s.archived]
                if main_after
                else None,
                "make_pipeline": None
                if existing
                else {"key": target["key"], "name": target["name"], "sources": target["sources"]},
                "pipeline_stages": [s.label for s in target_after if not s.archived]
                if target_after
                else None,
                "move_leads": len(leads),
                "move_by_stage": {
                    kind: {
                        "leads": count,
                        "lands_in": (lands.resolve(kind, None) or lands.stages[0]).label,
                    }
                    for kind, count in sorted(by_kind.items())
                },
                # [stage now, stage after, leads]: every lead, moving or staying.
                "move_map": [[now, after, n] for (now, after), n in sorted(moves.items())],
                "main_map": [[now, after, n] for (now, after), n in sorted(stays.items())],
                "main_leads_after": sum(stays.values()),
            }
            if not (rename or main_after or existing is None or target_after or leads):
                report["status"] = "already_applied"
                print(json.dumps(report))
                return 0
            if not apply:
                report["status"] = "eligible"
                print(json.dumps(report))
                return 0
            now = datetime.now(UTC)
            if rename:
                await pipelines.change(
                    db, tenant_id, pipelines.MAIN, name=main_spec["name"], by=approver, now=now
                )
            if main_after:
                await journeys.save(
                    db,
                    tenant_id,
                    stages=main_after,
                    industry=main_before.industry,
                    expected_version=main_before.version,
                    note=journeys.change_note(main_before, main_after),
                    by=approver,
                    now=now,
                    pipeline=pipelines.MAIN,
                )
            if existing is None:
                made = await pipelines.create(
                    db,
                    tenant_id,
                    name=target["name"],
                    sources=target["sources"],
                    by=approver,
                    now=now,
                )
                if made.key != target["key"]:
                    raise SystemExit(json.dumps({"refused": "pipeline_key_differs", **report}))
            if target_after:
                await journeys.save(
                    db,
                    tenant_id,
                    stages=target_after,
                    industry=target.get("industry"),
                    expected_version=target_before.version,
                    note=journeys.change_note(target_before, target_after),
                    by=approver,
                    now=now,
                    pipeline=target["key"],
                )
            desk = LeadDesk(
                db,
                Viewer(person_id=approver, tenant_id=tenant_id, role="owner", name="Data change"),
                now=now,
            )
            for lead in leads:
                await desk.move_pipeline(
                    lead.id,
                    pipeline=target["key"],
                    expected_revision=lead.revision,
                    command_id=uuid5(command_id, f"move:{lead.id}"),
                )
            await append_audit_event(
                db,
                tenant_id=tenant_id,
                actor_person_id=approver,
                actor_type="operator",
                action="lead_desk.pipelines_data_change",
                resource_type="tenant",
                resource_id=tenant_id,
                request_id=str(uuid5(command_id, "audit")),
                reason="Owner decision 22 Oct 2026: partner leads and enquiries as two pipelines",
                payload={
                    "issue": spec.get("issue"),
                    "command_id": str(command_id),
                    "renamed_main": main_spec.get("name") if rename else None,
                    "main_stages_saved": bool(main_after),
                    "pipeline": target["key"],
                    "pipeline_made": existing is None,
                    "pipeline_stages_saved": bool(target_after),
                    "leads_moved": len(leads),
                },
            )
            report["status"] = "applied"
    finally:
        await engine.dispose()
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--apply"]
    raise SystemExit(asyncio.run(main(args[0], "--apply" in sys.argv[1:])))
