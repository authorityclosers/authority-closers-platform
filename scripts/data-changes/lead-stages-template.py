"""Install a kind of business's stages for one organisation and place its leads (approved
data change).

Owner, 25 Oct 2026 (through the orchestrator): the sales team's nine stages ("Inside sales
with demos") live for the Authority Closers organisation. This is the product's own
install (Leads -> Lead stages -> pick a kind of business; ``POST /journey/template`` with
its map), done once, in one transaction, for one organisation:
  1. the template's stages become the pipeline's list: a new version, the old stages stay
     archived, so the history keeps its words;
  2. the leads of each old stage the map names move to the new stage picked, through the
     app's own move (``LeadDesk.place_leads``): one history line each, source "stages
     changed", which ad platforms and the pipeline's numbers skip. An old stage the map
     leaves out keeps its leads where the app puts them (its own stage, or the live stage
     of its kind). The app allows open stages to go to open stages only, and Won and Lost
     to stay their kind: nothing becomes Junk here;
  3. one audit event naming the approver and the issue.
Nothing is deleted. A dry run (the default) reads in a read-only transaction and takes no
locks; a rerun after apply finds nothing to do.

A template that changed since an organisation installed it (owner, 25 Oct 2026: the sales
team's eight stages, Junk no longer a stage) installs again the same way: its stages renamed and
ordered as the template says, and the map placing the leads (Junk to Lost, "Junk / not a real
lead", where the new list has no Junk). An organisation whose live stages already read as the
template's is "already_applied".

Run inside the API container with the deployed settings (its filesystem is read-only, so
the input goes inline):
    docker exec -i <api> python - '<input JSON>' [--apply] < lead-stages-template.py
input: {"command_id", "tenant": its id or its first 8 characters, "approver_email",
        "issue", "template": "inside_sales_demos", "pipeline": "main" (default),
        "map": {"<old stage key>": "<new stage key>", ...}}
Prints stage names, keys and counts only; never a lead's name or number.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.settings import get_settings
from ac_platform.audit.service import append_audit_event
from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.journey.templates import TEMPLATES
from ac_platform.lead_desk.store import LeadDesk, Viewer


def _input(path: str) -> dict[str, Any]:
    """The input, inline JSON or a file."""
    if path.lstrip().startswith("{"):
        return dict(json.loads(path))
    with open(path, encoding="utf-8") as file:
        return dict(json.load(file))


async def _tenant(db: AsyncSession, given: str) -> UUID:
    """The organisation: its id, or the first characters of it when only one starts so."""
    given = given.strip().lower()
    if len(given) == 36:
        return UUID(given)
    if len(given) < 8 or not all(ch in "0123456789abcdef" for ch in given):
        raise SystemExit(json.dumps({"refused": "tenant_prefix_needs_8_hex_characters"}))
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
    if len(found) != 1:
        raise SystemExit(json.dumps({"refused": "tenant_prefix_matches", "matches": len(found)}))
    return UUID(str(found[0]))


async def _landings(
    db: AsyncSession,
    tenant_id: UUID,
    before: journeys.Journey,
    after: journeys.Journey,
    places: dict[str, str],
) -> list[dict[str, Any]]:
    """Where today's leads land, by the stage they show now: names, keys and counts."""
    moves: Counter[tuple[str, str]] = Counter()
    for (kind, step), leads in (await journeys.lead_pairs(db, tenant_id, before)).items():
        old = before.column(kind, step)
        new = journeys.landing(before, after, places, kind, step)
        moves[(old.key, new.key)] += leads
    old_labels = {stage.key: stage.label for stage in before.stages}
    new_labels = {stage.key: stage.label for stage in after.stages}
    return [
        {
            "from": old_labels.get(old, old),
            "from_key": old,
            "to": new_labels.get(new, new),
            "to_key": new,
            "leads": count,
        }
        for (old, new), count in sorted(moves.items(), key=lambda item: -item[1])
    ]


async def run(
    db: AsyncSession, spec: dict[str, Any], *, apply: bool, now: datetime
) -> dict[str, Any]:
    """The plan, or the change made, inside the caller's transaction."""
    command_id = UUID(spec["command_id"])
    template_id = str(spec["template"])
    key = str(spec.get("pipeline") or journeys.MAIN_PIPELINE)
    wanted = {str(old): str(new) for old, new in dict(spec.get("map") or {}).items()}
    profile = next((item for item in TEMPLATES if item.id == template_id), None)
    if profile is None:
        raise SystemExit(json.dumps({"refused": "unknown_template", "template": template_id}))
    if not apply:
        # A dry run never writes, and holds no lock on anyone's work.
        await db.execute(text("SET TRANSACTION READ ONLY"))
    tenant_id = await _tenant(db, str(spec["tenant"]))
    approver = (
        await db.execute(
            text("select id from persons where lower(email) = :e"),
            {"e": str(spec["approver_email"]).strip().lower()},
        )
    ).scalar_one_or_none()
    report: dict[str, Any] = {
        "mode": "apply" if apply else "dry-run",
        "tenant_id": str(tenant_id),
        "pipeline": key,
        "template": template_id,
        "approver_found": approver is not None,
    }
    if apply:
        if approver is None:
            raise SystemExit(json.dumps({"refused": "approver_not_found", **report}))
        # One writer at a time for this organisation's stages.
        await db.execute(text("select id from tenants where id = :t for update"), {"t": tenant_id})
    before = await journeys.read(db, tenant_id, key)
    counts = await journeys.lead_counts(db, tenant_id, before)
    stages = journeys.from_template(template_id, before, counts)
    after = journeys.Journey(before.version + 1, template_id, stages, pipeline=key)
    # Installed already, as the template reads today: nothing to do. A template that changed
    # since (renamed, reordered, a stage gone) installs again with the map.
    current = before.industry == template_id and [
        (stage.key, stage.label) for stage in before.live
    ] == [(item.key, item.label) for item in profile.stages]
    if current:
        # A rerun after apply: the map was for the old list. Some old keys are new keys
        # too ("interested"), so applying it again would move leads already placed.
        wanted = {}
    try:
        places = journeys.check_places(before, after, wanted)
    except journeys.JourneyError as error:
        raise SystemExit(json.dumps({"refused": "map", "why": str(error), **report})) from None
    landings = await _landings(db, tenant_id, before, after, places)
    report["before"] = {
        "version": before.version,
        "industry": before.industry,
        "stages": [
            {
                "key": stage.key,
                "label": stage.label,
                "kind": stage.kind,
                "leads": counts.get(stage.key, 0),
            }
            for stage in before.live
        ],
    }
    report["after"] = {
        "stages": [
            {"key": stage.key, "label": stage.label, "kind": stage.kind}
            for stage in stages
            if not stage.archived
        ],
    }
    report["choices"] = {
        old: list(new) for old, new in journeys.place_choices(before, after).items()
    }
    report["map"] = places
    report["landings"] = landings
    report["leads"] = sum(item["leads"] for item in landings)
    if current:
        # Installed already: the list is this template's and its leads were placed then.
        report["status"] = "already_applied"
        return report
    if not apply:
        report["status"] = "eligible"
        return report
    assert approver is not None
    saved = await journeys.save(
        db,
        tenant_id,
        stages=stages,
        industry=template_id,
        expected_version=before.version,
        note=f"Used the {profile.name} stages (approved data change, {spec.get('issue')})",
        by=approver,
        now=now,
        pipeline=key,
    )
    desk = LeadDesk(
        db,
        Viewer(person_id=approver, tenant_id=tenant_id, role="owner", name="Data change"),
        now=now,
    )
    moved = await desk.place_leads(before, saved, places)
    await append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_person_id=approver,
        actor_type="operator",
        action="lead_desk.stages_template_data_change",
        resource_type="tenant",
        resource_id=tenant_id,
        request_id=str(uuid5(command_id, "audit")),
        reason=f"Owner approval: the {profile.name} stages, with the map in the payload",
        payload={
            "issue": spec.get("issue"),
            "command_id": str(command_id),
            "template": template_id,
            "pipeline": key,
            "version": saved.version,
            "map": places,
            "leads_moved": moved,
        },
    )
    report["version"] = saved.version
    report["leads_moved"] = moved
    report["status"] = "applied"
    return report


async def main(path: str, apply: bool) -> int:
    spec = _input(path)
    engine = create_async_engine(get_settings().database_url)
    try:
        async with async_sessionmaker(engine)() as db, db.begin():
            report = await run(db, spec, apply=apply, now=datetime.now(UTC))
    finally:
        await engine.dispose()
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--apply"]
    raise SystemExit(asyncio.run(main(args[0], "--apply" in sys.argv[1:])))
