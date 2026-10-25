"""Create a fictional test organisation with a kind of business's stages and fictional
leads (approved data change).

Owner, 25 Oct 2026 (AUT-2221, through the orchestrator): a made-up rooftop solar business,
"Sunrise Rooftops", in production Sales X-Ray, for the team-workspace task of the usability
test kit (docs/research/2026-10-25-sales-intelligence-programme/07-usability-test-kit.md,
Task 1 variant B). In one transaction, through the app's own code:
  1. the organisation, as an operator creates one (``OrganisationService.create``,
     idempotent by command id), with the given person as its Owner;
  2. the template's stages, as Leads -> Lead stages installs them (``journeys.save``);
  3. the Owner takes no new leads (Leads -> Team), so the waiting leads stay unassigned;
  4. twelve fictional leads, every one marked test data (reports, the SLA, call insights,
     Meta conversions and partner events skip test data): ten with the Owner, spread over
     the stages by the app's own moves (one history line each; a meeting booked, and two
     held, as the app books and holds them), and two New leads nobody holds, the newest;
  5. one audit event naming the approver and the issue.
No real person, company or number: the names are made up and the phones are empty.

A dry run (the default) makes the whole change in its transaction, reports it and rolls it
back: it proves the apply on the live data and leaves nothing. A rerun after apply finds
the organisation by its command id and changes nothing. ``--read`` reads the result back in
a read-only transaction.

Run inside the API container with the deployed settings (its filesystem is read-only, so
the input goes inline):
    docker exec -i <api> python - '<input JSON>' [--apply | --read] < test-organisation.py
input: {"command_id", "name", "owner_email", "approver_email", "issue",
        "template": "inside_sales_demos"}
Prints the fictional leads' names, stage keys, counts and masked emails only.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Final, Literal, NamedTuple
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.settings import get_settings
from ac_platform.audit.service import append_audit_event
from ac_platform.identity.models import Person
from ac_platform.lead_desk import meetings as meeting_rows
from ac_platform.lead_desk.contracts import (
    MeetingDone,
    MeetingInput,
    NewLead,
    RepRules,
    StageMove,
)
from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.journey.templates import TEMPLATES
from ac_platform.lead_desk.models import Lead, LeadMeeting
from ac_platform.lead_desk.store import DEFAULT_MAX_OPEN, LeadDesk, Viewer
from ac_platform.organisations.service import OrganisationService
from ac_platform.tenancy.models import Membership, Organisation, Tenant

Mode = Literal["dry-run", "apply", "read"]
IST: Final = ZoneInfo("Asia/Kolkata")
ACTION: Final = "lead_desk.test_organisation_data_change"


class Spot(NamedTuple):
    """A fictional lead and where it ends: a stage of the template, or "waiting" (New,
    nobody holds it yet). A named tuple: the script also loads as a plain file."""

    name: str
    company: str | None
    city: str
    interest: str
    language: str
    place: str


# Made up: no real person, company or number.
SUNRISE: Final[tuple[Spot, ...]] = (
    Spot("Anita Sample", None, "Pune", "3 kW rooftop for a home", "Marathi", "new"),
    Spot("Vikram Example", "Example Cold Storage", "Nashik", "25 kW factory roof", "Hindi", "new"),
    Spot("Neha Demo", None, "Nagpur", "5 kW with battery backup", "Hindi", "not_connected"),
    Spot(
        "Arjun Sample",
        "Sample Public School",
        "Kolhapur",
        "15 kW school roof",
        "Marathi",
        "interested",
    ),
    Spot("Kavya Example", None, "Pune", "3 kW rooftop, subsidy question", "English", "interested"),
    Spot(
        "Rahul Demo",
        "Demo Textiles",
        "Aurangabad",
        "40 kW factory roof",
        "Hindi",
        "discussion_incomplete",
    ),
    Spot("Pooja Sample", None, "Satara", "4 kW rooftop for a home", "Marathi", "meeting_scheduled"),
    Spot(
        "Sameer Example",
        "Example Dairy Farm",
        "Ahmednagar",
        "10 kW with a solar pump",
        "Marathi",
        "demo_completed",
    ),
    Spot("Divya Demo", None, "Pune", "5 kW rooftop for a home", "English", "won"),
    Spot("Imran Sample", "Sample Hardware Store", "Solapur", "6 kW shop roof", "Hindi", "lost"),
    Spot("Lata Example", None, "Sangli", "3 kW rooftop for a home", "Marathi", "waiting"),
    Spot("Farhan Demo", "Demo Bakery", "Pune", "8 kW shop roof", "Hindi", "waiting"),
)


def _input(path: str) -> dict[str, Any]:
    """The input, inline JSON or a file."""
    if path.lstrip().startswith("{"):
        return dict(json.loads(path))
    with open(path, encoding="utf-8") as file:
        return dict(json.load(file))


def _mask(email: str | None) -> str:
    if not email or "@" not in email:
        return "[none]"
    local, domain = email.rsplit("@", 1)
    return f"{local[:1]}***@{domain}"


def _at(now: datetime, days: int, hour: int, minute: int = 0) -> datetime:
    """A time of day in India, some days from now's date there."""
    day: date = now.astimezone(IST).date() + timedelta(days=days)
    return datetime.combine(day, time(hour, minute), tzinfo=IST)


async def _person(db: AsyncSession, email: str) -> Person | None:
    found: Person | None = await db.scalar(
        select(Person).where(func.lower(Person.email) == email.strip().lower())
    )
    return found


async def _created(db: AsyncSession, command_id: UUID) -> Organisation | None:
    found: Organisation | None = await db.scalar(
        select(Organisation).where(Organisation.creation_command_id == command_id)
    )
    return found


def _stage_key(journey: journeys.Journey, stage: str, step: str | None) -> str:
    found = journey.resolve(stage, step)
    return found.key if found is not None else stage


async def _readback(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
    """The organisation as the app sees it: members, stages with their leads, test data."""
    tenant = await db.get(Tenant, tenant_id)
    assert tenant is not None
    members = (
        await db.execute(
            select(Membership.role, Membership.status, Person.email)
            .join(Person, Person.id == Membership.person_id)
            .where(Membership.tenant_id == tenant_id, Membership.ended_at.is_(None))
            .order_by(Membership.role)
        )
    ).all()
    journey = await journeys.read(db, tenant_id, journeys.MAIN_PIPELINE)
    counts = await journeys.lead_counts(db, tenant_id, journey)
    leads = (
        await db.execute(
            select(Lead.name, Lead.stage, Lead.step, Lead.owner_person_id, Lead.test_data)
            .where(Lead.tenant_id == tenant_id)
            .order_by(Lead.created_at, Lead.name)
        )
    ).all()
    meetings = Counter(
        (
            await db.scalars(select(LeadMeeting.status).where(LeadMeeting.tenant_id == tenant_id))
        ).all()
    )
    return {
        "tenant_id": str(tenant_id),
        "name": tenant.name,
        "handle": tenant.slug,
        "members": [
            {"role": role, "status": status, "email": _mask(email)}
            for role, status, email in members
        ],
        "stages": {
            "version": journey.version,
            "industry": journey.industry,
            "live": [
                {"key": stage.key, "label": stage.label, "leads": counts.get(stage.key, 0)}
                for stage in journey.live
            ],
        },
        "leads": [
            {
                "name": name,
                "stage": _stage_key(journey, stage, step),
                "held": owner is not None,
                "test_data": test_data,
            }
            for name, stage, step, owner, test_data in leads
        ],
        "meetings": dict(meetings),
    }


async def _place(
    earlier: LeadDesk, later: LeadDesk, lead: Lead, spot: Spot, command_id: UUID, now: datetime
) -> None:
    """Moves the lead to its stage as a seller would, one step at a time."""

    def key(step: str) -> UUID:
        return uuid5(command_id, f"{spot.name}:{step}")

    async def move(desk: LeadDesk, step: str, **given: Any) -> None:
        nonlocal lead
        lead = await desk.move(
            lead.id,
            StageMove(
                command_id=key(step),
                expected_revision=lead.revision,
                step=step,
                via="api",
                **given,
            ),
        )

    if spot.place in ("new", "waiting"):
        return
    if spot.place == "not_connected":
        await move(
            earlier, "not_connected", nc_reason="did_not_pick", next_action_at=_at(now, 1, 10, 30)
        )
    elif spot.place in ("interested", "discussion_incomplete"):
        days = 2 if spot.name.endswith("Example") else 1
        await move(earlier, spot.place, next_action_at=_at(now, days, 11))
    elif spot.place == "lost":
        await move(earlier, "lost", outcome_reason="price")
    elif spot.place == "meeting_scheduled":
        await move(
            earlier,
            "meeting_scheduled",
            meeting=MeetingInput(
                starts_at=_at(now, 1, 16),
                duration_minutes=30,
                mode="phone",
                agenda="Roof survey and quote (fictional)",
            ),
        )
    elif spot.place in ("demo_completed", "won"):
        # Booked for an hour ago, held, then (Won) closed.
        await move(
            earlier,
            "meeting_scheduled",
            meeting=MeetingInput(
                starts_at=now - timedelta(hours=1),
                duration_minutes=30,
                mode="phone",
                agenda="Roof survey and quote (fictional)",
            ),
        )
        booked = await meeting_rows.open_meeting(later.db, later.tenant_id, lead.id)
        assert booked is not None
        lead = await later.meeting_done(
            booked.id,
            MeetingDone(
                command_id=key("held"),
                expected_revision=lead.revision,
                note="Shared the quote (fictional).",
                next_action_at=_at(now, 3, 12),
            ),
        )
        if spot.place == "won":
            await move(later, "won")
    else:
        raise SystemExit(json.dumps({"refused": "unknown_place", "place": spot.place}))


async def run(
    db: AsyncSession,
    spec: dict[str, Any],
    *,
    mode: Mode,
    now: datetime,
    boundaries: tuple[UUID, UUID],
) -> dict[str, Any]:
    """The change, its rehearsal, or its read-back, inside the caller's transaction."""
    command_id = UUID(spec["command_id"])
    name = str(spec["name"]).strip()
    template_id = str(spec.get("template") or "inside_sales_demos")
    profile = next((item for item in TEMPLATES if item.id == template_id), None)
    if profile is None:
        raise SystemExit(json.dumps({"refused": "unknown_template", "template": template_id}))
    if any(
        spot.place not in {"waiting", *(stage.key for stage in profile.stages)} for spot in SUNRISE
    ):
        raise SystemExit(json.dumps({"refused": "fixture_stage_not_in_template"}))
    if mode == "read":
        await db.execute(text("SET TRANSACTION READ ONLY"))
    owner = await _person(db, str(spec["owner_email"]))
    approver = await _person(db, str(spec["approver_email"]))
    report: dict[str, Any] = {
        "mode": mode,
        "name": name,
        "template": template_id,
        "owner": _mask(owner.email if owner else None),
        "owner_found": owner is not None,
        "approver_found": approver is not None,
    }
    prior = await _created(db, command_id)
    if prior is not None:
        report["status"] = "already_applied" if mode != "read" else "read"
        report["organisation"] = await _readback(db, prior.tenant_id)
        return report
    if mode == "read":
        report["status"] = "not_found"
        return report
    if owner is None or approver is None:
        raise SystemExit(json.dumps({"refused": "person_not_found", **report}))
    # The same organisation made by another request: never a second one.
    twin = await db.scalar(
        select(Tenant.id)
        .join(Membership, Membership.tenant_id == Tenant.id)
        .where(
            Membership.person_id == owner.id,
            Membership.ended_at.is_(None),
            func.lower(Tenant.name) == name.lower(),
        )
        .limit(1)
    )
    if twin is not None:
        raise SystemExit(json.dumps({"refused": "owner_has_one_by_this_name", **report}))

    created = await OrganisationService(
        db, operations_tenant_id=boundaries[0], public_learner_tenant_id=boundaries[1]
    ).create(
        name,
        owner.id,
        command_id,
        f"approved-data-change:{spec.get('issue')}",
        reason=f"Fictional test organisation for the usability test kit ({spec.get('issue')})",
    )
    tenant_id = created.tenant_id
    before = await journeys.read(db, tenant_id, journeys.MAIN_PIPELINE)
    stages = journeys.from_template(template_id, before, {})
    saved = await journeys.save(
        db,
        tenant_id,
        stages=stages,
        industry=template_id,
        expected_version=before.version,
        note=f"Used the {profile.name} stages (approved data change, {spec.get('issue')})",
        by=owner.id,
        now=now,
        pipeline=journeys.MAIN_PIPELINE,
    )

    def desk(at: datetime) -> LeadDesk:
        return LeadDesk(
            db,
            Viewer(person_id=owner.id, tenant_id=tenant_id, role="owner", name="Test data"),
            sandbox=True,
            now=at,
        )

    earlier = desk(now - timedelta(hours=3))
    later = desk(now)
    # The Owner takes no new leads, so the waiting ones stay unassigned (Task 1 variant B).
    await later.save_rep(
        owner.id, RepRules(expected_revision=0, available=False, max_open=DEFAULT_MAX_OPEN)
    )
    for index, spot in enumerate(SUNRISE):
        waiting = spot.place == "waiting"
        detail = await (later if waiting else earlier).add(
            NewLead(
                command_id=uuid5(command_id, f"lead:{index}"),
                name=spot.name,
                company=spot.company,
                city=spot.city,
                interest=spot.interest,
                language=spot.language,
                assign="rules" if waiting else "me",
            )
        )
        lead = await db.get(Lead, detail.lead.lead_id)
        assert lead is not None
        await _place(earlier, later, lead, spot, command_id, now)
    await db.flush()
    await append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_person_id=approver.id,
        actor_type="operator",
        action=ACTION,
        resource_type="tenant",
        resource_id=tenant_id,
        request_id=str(uuid5(command_id, "audit")),
        reason=f"Owner approval: a fictional test organisation, {name}",
        payload={
            "issue": spec.get("issue"),
            "command_id": str(command_id),
            "template": template_id,
            "version": saved.version,
            "leads": len(SUNRISE),
            "test_data": True,
        },
    )
    report["organisation"] = await _readback(db, tenant_id)
    report["status"] = "applied" if mode == "apply" else "rehearsed_and_rolled_back"
    return report


async def execute(
    sessions: async_sessionmaker[AsyncSession],
    spec: dict[str, Any],
    *,
    mode: Mode,
    now: datetime,
    boundaries: tuple[UUID, UUID],
) -> dict[str, Any]:
    """One transaction: committed on apply, rolled back otherwise."""
    async with sessions() as db:
        try:
            report = await run(db, spec, mode=mode, now=now, boundaries=boundaries)
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
    if settings.operations_tenant_id is None or settings.public_learner_tenant_id is None:
        raise SystemExit(json.dumps({"refused": "tenant_boundaries_not_configured"}))
    engine = create_async_engine(settings.database_url)
    try:
        report = await execute(
            async_sessionmaker(engine, expire_on_commit=False),
            _input(path),
            mode=mode,
            now=datetime.now(UTC),
            boundaries=(settings.operations_tenant_id, settings.public_learner_tenant_id),
        )
    finally:
        await engine.dispose()
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    chosen: Mode = "apply" if "--apply" in flags else "read" if "--read" in flags else "dry-run"
    raise SystemExit(asyncio.run(main(args[0], chosen)))
