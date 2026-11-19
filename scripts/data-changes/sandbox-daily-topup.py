"""Today's work in a sandbox organisation, played up to now (approved data change).

The owner, 14 Nov 2026 (via the orchestrator and live-design): "make a nice sales inbox… live
data… so my dev can continuously continue with the new numbers". The dev AC Sales Sandbox's
30-day history (``sandbox-organisations.py``) ended on 30 Oct, so Home read 0 for Today.

Each run plays one day (India time) of the sandbox's own sellers, through the app's own code,
up to ``until`` (default now):
- the phone's call history for every call each seller places (start and seconds; about 60%
  not connected), then the seller's after-call answer: follow-ups with call-back tasks, open
  talks, interest, meetings booked, wins, losses and junk with their reasons;
- a few Call-button dials the phone never timed and the seller answered "We talked": unknown,
  neither connected nor not (Dipak's honest numbers, 3 Nov 2026);
- new enquiries from the organisation's ads and website, given out by its own rules.
Calls follow due and late follow-ups first, then new and untried leads; some due follow-ups
are left for another day, so Home shows late ones. The last calls are minutes old, so the team
floor says "Called recently" during work hours (the app never guesses "on a call").

Every slot of the day is planned from the date alone (same date, same plan) and keyed by its
command id. A rerun skips the slots already written and plays the ones whose time has come, so
a timer can run it every 15 minutes. Sunday plays only when the organisation works Sundays
(``include_sunday`` adds Sunday to its work hours: the server drops calls outside them).

Refuses outside a sandbox organisation (``conversation_sandbox_organisations``). Outside the
development environment it also refuses any organisation but a TEST workspace: its name starts
with "TEST · " and every lead it holds is test data (owner, 19 Nov 2026: "show the app to
investors"; the production TEST · Sahyadri Homes' 14 days ended on 14 Nov). A dry run (the
default) makes the change and rolls it back; ``--apply`` commits; ``--plan`` prints the day's
plan and writes nothing. ``days`` plays several days in order, in the one transaction.

In production the API container's filesystem is read-only: pipe the script in and put the
input in its tmpfs ``/tmp`` first:
    docker exec -i <api> python - /tmp/topup.json [--apply | --plan] < sandbox-daily-topup.py

Run on ac as root with the dev-live API's settings and Python:
    set -a; . /etc/authority-closers/development/api-live.env; set +a
    $SLOT/.venv/bin/python scripts/data-changes/sandbox-daily-topup.py <input.json> \
        [--apply | --plan]
input: {"command_id", "approver_email", "issue", "tenant_id",
        "day"?: "YYYY-MM-DD" (India time; default today), "until"?: ISO time (default now),
        "days"?: ["YYYY-MM-DD", ...] (several days, oldest first; instead of "day"),
        "include_sunday"?: false,
        "exclude_person_ids"?: [members who are not the sandbox's sellers, e.g. a QA account]}
Prints counts and the plan's size; never a lead's details.
"""

from __future__ import annotations

import asyncio
import json
import random
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Final, Literal
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.settings import get_settings
from ac_platform.audit.service import append_audit_event
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
)
from ac_platform.identity.models import Person
from ac_platform.lead_desk import tasks as task_book
from ac_platform.lead_desk.contracts import (
    Disposition,
    MeetingInput,
    PhoneLog,
    PhoneLogCall,
    TaskCommand,
    WorkHoursCommand,
)
from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.models import Lead, LeadEvent
from ac_platform.lead_desk.store import LeadDesk, Viewer
from ac_platform.tenancy.models import Membership, Tenant

Mode = Literal["dry-run", "apply", "plan"]
IST: Final = ZoneInfo("Asia/Kolkata")
ACTION: Final = "lead_desk.sandbox_daily_topup"
TEST_PREFIX: Final = "TEST · "
DAY_START: Final = time(10, 30)
DAY_END: Final = time(19, 0)
LUNCH: Final = (time(13, 30), time(14, 15))
SUNDAY_HOURS: Final = (time(11, 0), time(17, 0))
# The sandbox's stage list, found by meaning (as sandbox-organisations.py does).
MEANINGS: Final = {
    "new": "lead",
    "nc": "unreachable",
    "int": "qualified",
    "meet": "appointment_booked",
    "done": "appointment_done",
    "won": "won",
    "lost": "lost",
}
OPTIONAL_MEANINGS: Final = {"open": "contacted", "junk": "disqualified"}
CLOSED: Final = frozenset({"won", "lost", "junk"})
# The app's own reason keys, as sandbox-organisations.py uses them.
NC_REASONS: Final = (
    ("did_not_pick", 50),
    ("busy", 14),
    ("switched_off", 14),
    ("disconnected", 10),
    ("out_of_coverage", 6),
    ("not_in_use", 3),
    ("invalid_number", 3),
)
FIRST_LOST: Final = (
    ("not_interested", 40),
    ("price", 15),
    ("not_now", 18),
    ("chose_other", 10),
    ("not_a_fit", 17),
)
LATER_LOST: Final = (
    ("price", 30),
    ("chose_other", 20),
    ("not_now", 25),
    ("decided_not_to_proceed", 25),
)
JUNK_REASONS: Final = (
    ("invalid_number", 40),
    ("fake", 25),
    ("unusable_contact", 20),
    ("someone_else", 15),
)
OPEN_REASONS: Final = (("Call later", 55), ("Discussion incomplete", 45))
SOURCES: Final = (
    ("meta", "Meta Ads: Sales mastery webinar form", 22),
    ("meta", "Meta Ads: Closer career form", 18),
    ("webhook", "Google Ads: Sales coaching lead form", 22),
    ("webhook", "Website: /programme", 12),
    ("webhook", "YouTube: Closing skills video enquiry", 18),
)
INTERESTS: Final = (
    "12-week sales coaching programme",
    "High-ticket closer certification",
    "Sales training for my team",
    "1:1 sales coaching",
)
CITIES: Final = ("Pune", "Mumbai", "Thane", "Nashik", "Nagpur", "Kolhapur", "Bengaluru")
FIRST: Final = (
    "Rahul",
    "Sneha",
    "Amit",
    "Pooja",
    "Vikas",
    "Kavita",
    "Sanjay",
    "Neha",
    "Rakesh",
    "Swati",
    "Imran",
    "Lata",
    "Nitin",
    "Geeta",
    "Harish",
    "Jyoti",
    "Manoj",
    "Rekha",
    "Kunal",
    "Anita",
)
LAST: Final = (
    "Sharma",
    "Patil",
    "Joshi",
    "Desai",
    "Kale",
    "Shah",
    "Iyer",
    "Menon",
    "Gupta",
    "Pawar",
    "Rao",
    "Chavan",
    "Mehta",
    "Nair",
    "Bhosale",
    "Kapoor",
    "Reddy",
    "Sawant",
    "Verma",
    "Thakur",
)
DEALS: Final = (45000, 60000, 75000, 95000)
MEETING: Final = (
    "google_meet",
    "Programme walkthrough and fit check (fictional)",
    "https://meet.example.com/ac-sandbox",
)
PHONE_BLOCK: Final = 18000  # +91 00000 18xxx-19xxx: today's enquiries (no such Indian number)


def _refuse(reason: str, **extra: Any) -> SystemExit:
    return SystemExit(json.dumps({"refused": reason, **extra}, default=str))


def pick(rng: random.Random, weighted: Sequence[tuple[Any, float]]) -> Any:
    return rng.choices([item for item, _ in weighted], [w for _, w in weighted])[0]


def at(day: date, clock: time) -> datetime:
    return datetime.combine(day, clock, tzinfo=IST).astimezone(UTC)


# ----- the day's plan: pure, from the date and the seller alone ---------------------------


@dataclass(frozen=True)
class Seller:
    person_id: UUID
    name: str
    cold_only: bool
    inbound_only: bool


@dataclass(frozen=True)
class Slot:
    seller: int
    number: int
    start: datetime
    roll: float  # 0-1: how the call goes (connected or not, then the outcome)
    unknown: bool  # a Call-button dial the phone never timed


@dataclass(frozen=True)
class Arrival:
    number: int
    at: datetime
    source: tuple[str, str]
    record: dict[str, Any]


def seller_slots(
    base: UUID, day: date, index: int, seller: Seller, *, works: bool, sunday: bool
) -> list[Slot]:
    """One seller's calls on ``day``: when each starts and its dice, never in lunch, never
    overlapping (the plan leaves room for the longest talk), inside the day's hours."""
    if not works:
        return []
    rng = random.Random(uuid5(base, f"slots:{day}:{seller.person_id}").int)  # noqa: S311
    begin, end = SUNDAY_HOURS if sunday else (DAY_START, DAY_END)
    start = at(day, begin) + timedelta(minutes=rng.randint(0, 25))
    stop = at(day, end) - timedelta(minutes=rng.randint(0, 25))
    lunch = (at(day, LUNCH[0]), at(day, LUNCH[1]))
    gap = (2, 7) if seller.cold_only else (6, 16)
    count = rng.randint(30, 45) if seller.cold_only else rng.randint(14, 24)
    if sunday:
        count = max(4, count // 3)
    slots: list[Slot] = []
    moment = start
    for number in range(count):
        moment += timedelta(minutes=rng.uniform(*gap))
        if lunch[0] <= moment < lunch[1]:
            moment = lunch[1] + timedelta(minutes=rng.uniform(0, 8))
        if moment >= stop:
            break
        slots.append(
            Slot(index, number, moment.replace(microsecond=0), rng.random(), rng.random() < 0.06)
        )
        # The next call starts after this one could have ended (up to 15 minutes of talk).
        moment += timedelta(minutes=rng.uniform(1, 3) if rng.random() < 0.6 else rng.uniform(4, 15))
    return slots


def arrivals(base: UUID, day: date, *, sunday: bool) -> list[Arrival]:
    """Today's new enquiries: when, from where, and who (fictional)."""
    rng = random.Random(uuid5(base, f"arrivals:{day}").int)  # noqa: S311
    count = rng.randint(1, 4) if sunday else rng.randint(3, 10)
    out = []
    for number in range(count):
        moment = at(day, time(8, 0)) + timedelta(minutes=rng.uniform(0, 13 * 60))
        source = pick(rng, [((s, label), w) for s, label, w in SOURCES])
        phone = PHONE_BLOCK + (day.timetuple().tm_yday * 11 + number) % 2000
        record = {
            "name": f"{rng.choice(FIRST)} {rng.choice(LAST)}",
            "phone": f"+91 00000 {phone:05d}",
            "city": rng.choice(CITIES),
            "language": rng.choice(("Marathi", "Hindi", "English", "Hindi", "English")),
            "interest": rng.choice(INTERESTS),
        }
        out.append(Arrival(number, moment.replace(microsecond=0), source, record))
    return sorted(out, key=lambda item: item.at)


def outcome_for(phase: str, roll: float, *, cold: bool, rng: random.Random) -> tuple[bool, str]:
    """(connected, outcome) for a call on a lead in ``phase``; outcomes as the 30-day build."""
    chance = {
        "new": 0.24 if cold else 0.38,
        "nc": 0.18 if cold else 0.25,
        "open": 0.4,
        "int": 0.42,
        "done": 0.5,
    }.get(phase, 0.35)
    if roll >= chance:
        return False, "nc"
    if phase in ("new", "nc"):
        table = (
            (("int", 10), ("open", 12), ("meet", 2), ("lost", 56), ("junk", 14), ("later", 6))
            if cold
            else (("int", 30), ("open", 16), ("meet", 5), ("lost", 33), ("junk", 8), ("later", 8))
        )
    elif phase == "open":
        table = (("int", 33), ("again", 38), ("meet", 7), ("lost", 22))
    elif phase == "int":
        table = (("meet", 15), ("again", 45), ("lost", 27), ("later", 10), ("won", 3))
    else:
        table = (("won", 16), ("again", 48), ("lost", 36))
    return True, pick(rng, table)


def talk_seconds(rng: random.Random, outcome: str) -> int:
    low, high = {
        "lost": (35, 160),
        "junk": (20, 90),
        "int": (150, 660),
        "open": (120, 480),
        "again": (90, 420),
        "meet": (300, 900),
        "won": (480, 1500),
        "later": (25, 80),
    }[outcome]
    return round(rng.uniform(low, high))


def next_slot(
    rng: random.Random, after: datetime, *, days: tuple[int, int], work_days: Sequence[int]
) -> datetime:
    day = after.astimezone(IST).date() + timedelta(days=rng.randint(*days))
    while day.weekday() not in work_days:
        day += timedelta(days=1)
    return at(day, time(rng.randint(11, 17), rng.choice((0, 30))))


# ----- the app's own code --------------------------------------------------------------------


class _Desk(LeadDesk):
    """The app's desk; this script never reads a write's answer."""

    async def detail(self, lead_id: UUID) -> Any:  # noqa: ARG002
        return None


class Day:
    def __init__(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        base: UUID,
        day: date,
        until: datetime,
        spec: dict[str, Any],
    ) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.base = base
        self.day = day
        self.until = until
        self.spec = spec
        self.counter: Counter[str] = Counter()
        self.keys: dict[str, str] = {}
        self.phase_of: dict[str, str] = {}
        self.work_days: list[int] = []

    def key(self, *parts: object) -> UUID:
        return uuid5(self.base, ":".join(map(str, (self.day, *parts))))

    def desk(self, who: Seller | Person, role: str, now: datetime) -> _Desk:
        person = who.person_id if isinstance(who, Seller) else who.id
        name = who.name if isinstance(who, Seller) else (who.display_name or "Owner")
        return _Desk(
            self.db,
            Viewer(person_id=person, tenant_id=self.tenant_id, role=role, name=name),
            call_mode="simulated",
            sandbox=True,
            now=now,
        )

    async def stage_keys(self) -> None:
        journey = await journeys.read(self.db, self.tenant_id, journeys.MAIN_PIPELINE)
        for name, milestone in (*MEANINGS.items(), *OPTIONAL_MEANINGS.items()):
            stage = next((s for s in journey.live if s.milestone == milestone), None)
            if stage is not None:
                self.keys[name] = stage.key
            elif name in MEANINGS:
                raise _refuse("stage_list_lacks_a_meaning", meaning=milestone)
        self.phase_of = {key: name for name, key in self.keys.items()}

    async def people(self) -> tuple[Person, list[Seller]]:
        rows = (
            await self.db.execute(
                select(Membership.role, Person)
                .join(Person, Person.id == Membership.person_id)
                .where(Membership.tenant_id == self.tenant_id, Membership.ended_at.is_(None))
            )
        ).all()
        owner = next((p for role, p in rows if role == "owner"), None)
        if owner is None:
            raise _refuse("no_owner")
        sellers = []
        skip = {str(item) for item in self.spec.get("exclude_person_ids") or []}
        for role, person in sorted(rows, key=lambda r: str(r[1].id)):
            if role != "member" or str(person.id) in skip:
                continue
            name = person.display_name or "Seller"
            # The 30-day build's shapes: Aditya works the cold lists, Sneha only enquiries.
            sellers.append(
                Seller(person.id, name, name.startswith("Aditya"), name.startswith("Sneha"))
            )
        return owner, sellers

    async def done_today(self, command_ids: Sequence[UUID]) -> set[UUID]:
        found = await self.db.scalars(
            select(LeadEvent.command_id).where(
                LeadEvent.tenant_id == self.tenant_id, LeadEvent.command_id.in_(command_ids)
            )
        )
        return {item for item in found if item is not None}

    async def work_hours(self, owner: Person) -> None:
        desk = self.desk(owner, "owner", datetime.now(UTC))
        revision, config = await desk.settings()
        hours = config.get("work_hours") or {}
        self.work_days = list(hours.get("days") or [0, 1, 2, 3, 4, 5])
        if self.spec["include_sunday"] and 6 not in self.work_days:
            command: dict[str, Any] = {
                "expected_revision": revision,
                "days": [*self.work_days, 6],
                "start": hours.get("start") or DAY_START.strftime("%H:%M"),
                "end": hours.get("end") or DAY_END.strftime("%H:%M"),
                "pause_leads": bool(hours.get("pause_leads")),
            }
            if "breaks" in WorkHoursCommand.model_fields and hours.get("breaks"):
                command["breaks"] = hours["breaks"]
            await desk.save_work_hours(WorkHoursCommand(**command))
            self.work_days = command["days"]
            self.counter["work_hours_sunday_added"] += 1

    async def queue_for(self, seller: Seller, touched: set[UUID]) -> list[Lead]:
        """The seller's leads to call: due or late follow-ups first, then untried, then the rest."""
        end = at(self.day, DAY_END)
        rows = list(
            await self.db.scalars(
                select(Lead)
                .where(
                    Lead.tenant_id == self.tenant_id,
                    Lead.owner_person_id == seller.person_id,
                    Lead.phone.is_not(None),
                    Lead.stage.not_in(("won", "lost", "junk")),
                )
                .order_by(Lead.next_action_at.asc().nulls_last(), Lead.created_at.asc())
                .limit(400)
            )
        )
        rows = [
            lead
            for lead in rows
            if lead.id not in touched
            and self.phase(lead) not in CLOSED
            and self.phase(lead) != "meet"
        ]
        due = [
            lead for lead in rows if lead.next_action_at is not None and lead.next_action_at <= end
        ]
        fresh = [lead for lead in rows if lead.next_action_at is None and self.phase(lead) == "new"]
        rest = [lead for lead in rows if lead not in due and lead not in fresh]
        if seller.cold_only:
            return fresh + due + rest
        return due + fresh + rest

    def phase(self, lead: Lead) -> str:
        return self.phase_of.get(lead.step or "", "new")

    async def call(self, seller: Seller, slot: Slot, lead: Lead) -> None:
        rng = random.Random(self.key("dice", seller.person_id, slot.number).int)  # noqa: S311
        phase = self.phase(lead)
        cold = bool(getattr(lead, "pipeline", None) == "cold")
        connected, outcome = outcome_for(phase, slot.roll, cold=cold, rng=rng)
        dispose_id = self.key("dispose", seller.person_id, slot.number)
        if slot.unknown:
            # A Call-button dial: the desk opened the dialler; the phone never timed it and the
            # seller answered "We talked". Neither connected nor not connected.
            away = rng.randint(40, 300)
            await self.desk(seller, "member", slot.start + timedelta(seconds=away)).record_call(
                lead.id,
                command_id=self.key("dial", seller.person_id, slot.number),
                submission_id=None,
                simulated=False,
                duration_seconds=away,
                away=True,
            )
            await self.desk(seller, "member", slot.start + timedelta(seconds=away + 40)).dispose(
                lead.id,
                Disposition(
                    command_id=dispose_id,
                    expected_revision=lead.revision,
                    connected=True,
                    step=self.keys.get("open", self.keys["int"]),
                    follow_up_at=next_slot(rng, slot.start, days=(1, 2), work_days=self.work_days),
                    remark="Discussion incomplete: talked, wants to continue tomorrow (fictional).",
                ),
            )
            self.counter["calls_unknown"] += 1
            self.counter["calls"] += 1
            return
        seconds = talk_seconds(rng, outcome) if connected else 0
        ended = slot.start + timedelta(seconds=seconds + (0 if connected else rng.randint(18, 40)))
        await self.desk(
            seller, "member", ended + timedelta(seconds=rng.randint(30, 120))
        ).log_phone_calls(
            PhoneLog(
                device_id=uuid5(self.base, f"phone:{seller.person_id}"),
                calls=(
                    PhoneLogCall(
                        log_id=f"tu-{self.day:%m%d}-{str(seller.person_id)[:6]}-{slot.number}",
                        number=lead.phone or "",
                        started_at=slot.start,
                        duration_seconds=seconds,
                        direction="outgoing",
                    ),
                ),
            )
        )
        self.counter["calls"] += 1
        self.counter["connected" if connected else "not_connected"] += 1
        self.counter["talk_seconds"] += seconds
        now = ended + timedelta(seconds=rng.randint(15, 75))
        desk = self.desk(seller, "member", now)
        if not connected:
            reason = pick(rng, NC_REASONS)
            await desk.dispose(
                lead.id,
                Disposition(
                    command_id=dispose_id,
                    expected_revision=lead.revision,
                    connected=False,
                    reason=reason,
                ),
            )
            return
        await self.after_talk(seller, desk, lead, phase, outcome, now, dispose_id, rng)

    async def after_talk(
        self,
        seller: Seller,
        desk: _Desk,
        lead: Lead,
        phase: str,
        outcome: str,
        now: datetime,
        dispose_id: UUID,
        rng: random.Random,
    ) -> None:
        def go(**fields: Any) -> Disposition:
            return Disposition(
                command_id=dispose_id, expected_revision=lead.revision, connected=True, **fields
            )

        if outcome == "junk" and "junk" in self.keys:
            await desk.dispose(
                lead.id, go(step=self.keys["junk"], outcome_reason=pick(rng, JUNK_REASONS))
            )
            self.counter["junk"] += 1
            return
        if outcome in ("lost", "junk"):
            reason = (
                "not_a_lead"
                if outcome == "junk"
                else pick(rng, FIRST_LOST if phase in ("new", "nc") else LATER_LOST)
            )
            await desk.dispose(lead.id, go(step=self.keys["lost"], outcome_reason=reason))
            self.counter["lost"] += 1
            return
        if outcome == "won":
            await desk.dispose(
                lead.id,
                go(
                    step=self.keys["won"],
                    deal_value=str(rng.choice(DEALS)),
                    remark="Paid the first instalment (fictional).",
                ),
            )
            self.counter["won"] += 1
            return
        if outcome == "meet":
            starts = next_slot(rng, now, days=(1, 3), work_days=self.work_days)
            mode, agenda, link = MEETING
            await desk.dispose(
                lead.id,
                go(
                    step=self.keys["meet"],
                    follow_up_at=starts,
                    meeting=MeetingInput(
                        starts_at=starts,
                        duration_minutes=rng.choice((30, 45, 60)),
                        mode=mode,  # type: ignore[arg-type]
                        link=f"{link}/{lead.id.hex[:10]}",
                        location=None,
                        agenda=agenda,
                    ),
                ),
            )
            self.counter["meetings_booked"] += 1
            return
        if outcome == "later":
            follow = now + timedelta(hours=rng.choice((2, 3)))
            if follow.astimezone(IST).time() >= time(18, 30):
                follow = next_slot(rng, now, days=(1, 1), work_days=self.work_days)
        else:
            follow = next_slot(rng, now, days=(1, 3), work_days=self.work_days)
        stays = (
            phase
            if outcome == "again" and phase in ("open", "done")
            else (
                "open"
                if (outcome == "open" or (outcome == "later" and phase in ("new", "nc")))
                and "open" in self.keys
                else "int"
            )
        )
        if stays == "open":
            why = "Call later" if outcome == "later" else pick(rng, OPEN_REASONS)
            remark = f"{why}: " + rng.choice(
                ("Busy at work, call after 6.", "Driving, asked to call tomorrow.")
                if why == "Call later"
                else ("Line dropped mid-talk.", "Wants details first.")
            )
        else:
            remark = rng.choice(
                (
                    "Wants to discuss with family first.",
                    "Asked for the fee breakup.",
                    "Call back after salary day.",
                    "Comparing two options, keen.",
                )
            )
        await desk.dispose(lead.id, go(step=self.keys[stays], follow_up_at=follow, remark=remark))
        if rng.random() < 0.88:
            await task_book.TaskBook(desk).create(
                lead.id,
                TaskCommand(
                    command_id=uuid5(dispose_id, "call_back"),
                    kind="call_back",
                    starts_at=follow,  # type: ignore[arg-type]
                    source="after_call",
                    remind_before_minutes=10,
                ),
            )
            self.counter["call_back_tasks"] += 1
        self.counter["follow_ups_set"] += 1

    async def arrive(self, owner: Person, item: Arrival) -> None:
        ref = f"topup-{self.day:%Y%m%d}-{item.number}"
        if await self.db.scalar(
            select(Lead.id).where(Lead.tenant_id == self.tenant_id, Lead.source_ref == ref)
        ):
            self.counter["arrivals_already"] += 1
            return
        source, label = item.source
        _, outcome = await self.desk(owner, "owner", item.at).ingest(
            item.record,
            source=source,
            source_label=label,
            source_ref=ref,
            assign="rules",
            actor=None,
            test_data=True,
            command_id=self.key("arrive", item.number),
            received_at=item.at,
        )
        self.counter[f"arrivals_{outcome}"] += 1


async def test_workspace_only(db: AsyncSession, tenant_id: UUID) -> None:
    """Outside development: a TEST workspace only, every lead of it test data."""
    name = await db.scalar(select(Tenant.name).where(Tenant.id == tenant_id))
    if not isinstance(name, str) or not name.startswith(TEST_PREFIX):
        raise _refuse("test_workspace_only")
    real = await db.scalar(
        select(func.count())
        .select_from(Lead)
        .where(Lead.tenant_id == tenant_id, Lead.test_data.is_not(True))
    )
    if real:
        raise _refuse("test_workspace_holds_real_leads", leads=real)


async def play(
    db: AsyncSession,
    spec: dict[str, Any],
    *,
    mode: Mode,
    now: datetime,
    environment: str = "development",
) -> dict[str, Any]:
    tenant_id = UUID(spec["tenant_id"])
    if environment != "development":
        await test_workspace_only(db, tenant_id)
    if (
        await db.scalar(
            select(ConversationSandboxOrganisation.tenant_id).where(
                ConversationSandboxOrganisation.tenant_id == tenant_id
            )
        )
        is None
    ):
        raise _refuse("not_a_sandbox_organisation")
    approver = await db.scalar(
        select(Person).where(func.lower(Person.email) == spec["approver_email"].lower())
    )
    if approver is None:
        raise _refuse("approver_not_found")
    day = date.fromisoformat(spec["day"]) if spec.get("day") else now.astimezone(IST).date()
    until = min(now, datetime.fromisoformat(spec["until"])) if spec.get("until") else now
    base = UUID(spec["command_id"])
    work = Day(db, tenant_id, base, day, until, spec)
    await work.stage_keys()
    owner, sellers = await work.people()
    if mode != "plan":
        await work.work_hours(owner)
    else:
        revision, config = await work.desk(owner, "owner", now).settings()
        work.work_days = list((config.get("work_hours") or {}).get("days") or [0, 1, 2, 3, 4, 5])
    sunday = day.weekday() == 6
    works = day.weekday() in work.work_days or (sunday and spec["include_sunday"])
    plan = sorted(
        (
            slot
            for index, seller in enumerate(sellers)
            for slot in seller_slots(base, day, index, seller, works=works, sunday=sunday)
        ),
        key=lambda slot: (slot.start, slot.seller),
    )
    news = arrivals(base, day, sunday=sunday) if works else []
    due = [slot for slot in plan if slot.start <= until]
    report: dict[str, Any] = {
        "day": day.isoformat(),
        "until": until.isoformat(),
        "works": works,
        "sellers": len(sellers),
        "planned_calls": len(plan),
        "planned_arrivals": len(news),
        "due_calls": len(due),
        "due_arrivals": sum(1 for a in news if a.at <= until),
    }
    if mode == "plan":
        report["by_seller"] = Counter(sellers[slot.seller].name.split()[0] for slot in plan)
        return report
    for item in news:
        if item.at <= until:
            await work.arrive(owner, item)
    written = await work.done_today(
        [work.key("dispose", sellers[s.seller].person_id, s.number) for s in due]
    )
    touched: dict[int, set[UUID]] = {i: set() for i in range(len(sellers))}
    today_start = at(day, time(0, 0))
    for index, seller in enumerate(sellers):
        rows = await db.scalars(
            select(LeadEvent.lead_id).where(
                LeadEvent.tenant_id == tenant_id,
                LeadEvent.kind == "call",
                LeadEvent.actor_person_id == seller.person_id,
                LeadEvent.created_at >= today_start,
            )
        )
        touched[index] = set(rows)
    queues: dict[int, list[Lead]] = {}
    for slot in due:
        seller = sellers[slot.seller]
        if work.key("dispose", seller.person_id, slot.number) in written:
            work.counter["slots_already"] += 1
            continue
        if slot.seller not in queues:
            queues[slot.seller] = await work.queue_for(seller, touched[slot.seller])
        queue = queues[slot.seller]
        if not queue:
            work.counter["slots_no_lead"] += 1
            continue
        lead = queue.pop(0)
        touched[slot.seller].add(lead.id)
        await work.call(seller, slot, lead)
    await db.flush()
    await append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_person_id=approver.id,
        actor_type="operator",
        action=ACTION,
        resource_type="tenant",
        resource_id=tenant_id,
        request_id=str(uuid5(base, f"audit:{day}:{until:%H%M}")),
        reason=f"Owner approval ({spec['issue']}): a day's work in a sandbox organisation",
        payload={
            "issue": spec["issue"],
            "day": day.isoformat(),
            "until": until.isoformat(),
            "counts": dict(sorted(work.counter.items())),
        },
    )
    report["counts"] = dict(sorted(work.counter.items()))
    report["status"] = "applied" if mode == "apply" else "rehearsed_and_rolled_back"
    return report


def spec_of(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        body = json.load(handle)
    missing = [k for k in ("command_id", "approver_email", "issue", "tenant_id") if not body.get(k)]
    if missing:
        raise _refuse("missing_input", fields=missing)
    UUID(str(body["command_id"]))
    UUID(str(body["tenant_id"]))
    days = body.get("days") or []
    if days and (body.get("day") or sorted(days) != days or len(set(days)) != len(days)):
        raise _refuse("days_must_be_distinct_oldest_first_without_day")
    for item in days:
        date.fromisoformat(item)
    for item in body.get("exclude_person_ids") or []:
        UUID(str(item))
    return {**body, "include_sunday": body.get("include_sunday") is True}


async def main(path: str, mode: Mode) -> int:
    spec = spec_of(path)
    settings = get_settings()
    if settings.environment not in {"development", "staging", "production"}:
        raise _refuse("unknown_environment", environment=settings.environment)
    days = spec.get("days") or [spec.get("day")]
    engine = create_async_engine(settings.database_url, hide_parameters=True)
    reports: list[dict[str, Any]] = []
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            try:
                for day in days:
                    reports.append(
                        await play(
                            db,
                            {**spec, "day": day},
                            mode=mode,
                            now=datetime.now(UTC),
                            environment=settings.environment,
                        )
                    )
            except BaseException:
                await db.rollback()
                raise
            if mode == "apply":
                await db.commit()
            else:
                await db.rollback()
    finally:
        await engine.dispose()
    body: dict[str, Any] = reports[0] if len(reports) == 1 else {"days": reports}
    print(json.dumps({"approval": spec["issue"], **body}, default=str))
    return 0


if __name__ == "__main__":
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    chosen: Mode = "apply" if "--apply" in flags else "plan" if "--plan" in flags else "dry-run"
    raise SystemExit(asyncio.run(main(args[0], chosen)))
