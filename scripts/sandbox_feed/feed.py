"""The dev "AC Sales Sandbox", live every day (owner, 15 Nov 2026 ~01:45 IST: "a fresh data
server, a sandbox, e.g. AC Sales Sandbox, where data keeps coming live every day in proper
working hours, so we can test and see how things look"; with zeros on screen "we can't
understand anything").

A tick plays the sandbox's day from where the last tick stopped up to a little before now,
through the app's own lead desk as each person (the code the app's routes call): enquiries
arrive on Inbound, and the coach uploads a fresh Cold list when the last one runs low;
sellers dial (the phone logs each call with its real start and seconds), answer the
after-call sheet, set follow-ups, call-back and WhatsApp tasks, book and hold meetings, win,
lose and junk leads and write the odd note; a customer who already bought sometimes rings
in with a question (a call that isn't a sale). Sellers differ: Priya is the star, one seller
a day doesn't work, and Farah lets her follow-ups go overdue. Nothing here writes a count:
every number on a screen is the app counting what it stored, so the numbers add up.

It reuses the generator that built the sandbox (scripts/data-changes/sandbox-organisations.py):
its seller model, call outcomes, remarks, reasons and meeting handling.

DEV ONLY. It refuses unless AC_ENVIRONMENT is "development" and the workspace is the flagged
sandbox named "AC Sales Sandbox". Each run is one transaction; the moment it played up to
(its cursor) is an audit event in that transaction, so a crash replays nothing and a late
tick catches up. Dry run by default (everything made, reported, rolled back); --apply
commits.

    python feed.py setup     [--apply]  sixth seller, work hours, avatars, QA leads to History
    python feed.py tick      [--apply]  the cursor to now - 20 min (the timer, every ~12 min)
    python feed.py backfill  [--apply] [--from=YYYY-MM-DD]  whole days up to the last midnight
    python feed.py night     [--apply] [--pace N]  one-off: today 00:00 to now, compressed
    python feed.py read                 today's counts, read-only

Prints counts only: never a lead's name, phone or email.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any, Final, NamedTuple
from uuid import UUID, uuid5

HERE = Path(__file__).resolve().parent


def _generator() -> ModuleType:
    """The sandbox generator, beside this file once installed, or in the repo."""
    for path in (
        HERE / "sandbox-organisations.py",
        HERE.parent / "data-changes" / "sandbox-organisations.py",
    ):
        if path.is_file():
            loader = importlib.util.spec_from_file_location("sandbox_organisations_gen", path)
            assert loader is not None and loader.loader is not None
            module = importlib.util.module_from_spec(loader)
            sys.modules["sandbox_organisations_gen"] = module
            loader.loader.exec_module(module)
            return module
    raise SystemExit(json.dumps({"refused": "generator_missing"}))


gen = _generator()

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ac_platform.audit.models import AuditEvent  # noqa: E402
from ac_platform.audit.service import append_audit_event  # noqa: E402
from ac_platform.conversation_intelligence.synthetic_import_models import (  # noqa: E402
    ConversationSandboxOrganisation,
)
from ac_platform.identity.models import Person  # noqa: E402
from ac_platform.identity.repositories import AsyncSqlAlchemyIdentityRepository  # noqa: E402
from ac_platform.identity.sales_xray_profile_models import PersonPhoto  # noqa: E402
from ac_platform.identity.services import PersonSnapshot  # noqa: E402
from ac_platform.lead_desk.contracts import (  # noqa: E402
    FollowUp,
    NoteCommand,
    PhoneLog,
    PhoneLogCall,
    Reassign,
    RepRules,
    StageMove,
    WorkHoursCommand,
)
from ac_platform.lead_desk.history import HISTORY, worked  # noqa: E402
from ac_platform.lead_desk.models import (  # noqa: E402
    Lead,
    LeadEvent,
    LeadMeeting,
    LeadRep,
    LeadTask,
)
from ac_platform.lead_desk.store import counted_phone_call  # noqa: E402
from ac_platform.tenancy.models import Membership, Tenant  # noqa: E402

IST: Final = gen.IST
TENANT: Final = UUID("3100ddbc-4549-4a5e-85b8-421af6edd588")
NAME: Final = "AC Sales Sandbox"
# Every id the feed makes is uuid5 of this, so a window replayed makes the same ids.
FEED: Final = UUID("5f0e9a51-7c1d-4d4b-9a8e-15e1b2026c15")
ACTION: Final = "lead_desk.sandbox_feed"
OPENS: Final = time(9, 30)
CLOSES: Final = time(19, 30)
LUNCH: Final = (time(13, 30), time(14, 15))
DAYS: Final = (0, 1, 2, 3, 4, 5, 6)  # every day (owner: "every day in proper working hours")
LAG: Final = timedelta(minutes=20)  # a tick plays to now - LAG, so no call ends in the future
CATCH_UP: Final = timedelta(days=2)  # a tick plays at most this far back; older is backfill's
ARRIVALS: Final = (14, 24)  # Inbound enquiries a day
COLD_LOW: Final = 60  # a Cold seller with fewer untouched leads: the coach uploads a list
COLD_BATCH: Final = 150  # shared out to the sellers running low
ARCHIVE_AFTER: Final = timedelta(days=45)  # closed this long ago: the lead moves to History
NOTE_SHARE: Final = 0.12
# A seller's own clean-up, once a day: Not Connected leads nobody has reached for a week
# (or that ran out of tries) are closed as Lost, no response, at most this many each.
STALE_AFTER: Final = timedelta(days=7)
TIDY_PER_DAY: Final = 8
SUPPORT_CALLS: Final = (1, 3)  # customers ringing in with a question, a day
MAILBOX: Final = "admin@authorityclosers.com"
# The sixth seller: a long name, so the screens show how they cut names.
NEWCOMER: Final = ("Venkatesh", "Ramakrishnan", "ac.venkatesh")

Seller = gen.Seller
# Each seller's working style, by their sign-in alias. Priya: the star. Farah: leaves most
# due follow-ups for another day, so her tasks go overdue. Sneha takes only Inbound,
# Aditya only Cold.
PROFILES: Final[dict[str, Any]] = {
    "ac.priya": Seller(
        "Priya", "Deshmukh", "Pune", "ac.priya", 0, 3.2, 0.02, 0.01, 70, 1.15, 0, 1.35
    ),
    "ac.rohan": Seller("Rohan", "Patil", "Pune", "ac.rohan", 10, 5.0, 0.06, 0.05, 25, 1.0, 0, 1.0),
    "ac.sneha": Seller(
        "Sneha", "Iyer", "Mumbai", "ac.sneha", 15, 6.0, 0.08, 0.06, 0, 1.05, 0, 1.1, "inbound"
    ),
    "ac.aditya": Seller(
        "Aditya", "Joshi", "Pune", "ac.aditya", 25, 4.5, 0.25, 0.15, 55, 0.9, 0, 0.85, "cold"
    ),
    "ac.farah": Seller(
        "Farah", "Shaikh", "Mumbai", "ac.farah", 30, 7.5, 0.35, 0.6, 20, 0.95, 0, 0.85
    ),
    "ac.venkatesh": Seller(
        "Venkatesh", "Ramakrishnan", "Bengaluru", "ac.venkatesh", 5, 5.5, 0.1, 0.08, 30, 1.0, 0, 1.0
    ),
}
DEFAULT_PROFILE: Final = Seller("Seller", "", "Pune", "other", 15, 6.0, 0.1, 0.1, 15, 1.0, 0, 1.0)
STAR: Final = "ac.priya"
# The owner closes: each day the coach hands him one or two hot leads (Meeting Done or
# Interested) and he works only those, late in the morning and slowly, so his "Me" view on
# Home has calls, tasks and follow-ups of its own. Never idle, never Cold, never new
# enquiries (his rules keep him unavailable).
OWNER_PROFILE: Final = Seller(
    "Owner", "", "Pune", "owner", 75, 14.0, 0.3, 0.05, 0, 1.25, 0, 1.3, "inbound"
)
OWNER_BOOK: Final = 8  # open leads he holds at most
HANDOVER: Final = (1, 2)
# Who doesn't work today, in turn (never the star).
IDLE_TURN: Final = ("ac.rohan", "ac.sneha", "ac.venkatesh", "ac.aditya", "ac.farah")
# A stage key's meaning, for leads whose step is empty.
BY_STAGE: Final = {
    "new": "new",
    "not_connected": "nc",
    "follow_up": "open",
    "interested": "int",
    "won": "won",
    "lost": "lost",
    "junk": "junk",
}
NOTES: Final = (
    "Prefers WhatsApp over calls.",
    "Decision maker is the spouse; joins the next call.",
    "Asked for the fee breakup in writing.",
    "Comparing with one other programme.",
    "Wants weekend batch only.",
    "Budget fine; timing is the question.",
    "Referred by a past student.",
)
SUPPORT_NOTES: Final = (
    "Called in: asked about the batch timings (not a sale).",
    "Called in: needs the invoice for the first instalment (not a sale).",
    "Called in: could not open the class link (not a sale).",
    "Called in: wants to move to the weekend batch (not a sale).",
)
FICTIONAL: Final = re.compile(r"^\+?9100000\d{5}$")  # +91 00000 nnnnn


class Refused(SystemExit):
    def __init__(self, reason: str, **extra: Any) -> None:
        super().__init__(json.dumps({"refused": reason, **extra}))


# ----- the plan: pure ---------------------------------------------------------------------


def at(day: date, clock: time) -> datetime:
    return datetime.combine(day, clock, tzinfo=IST).astimezone(UTC)


def idle_on(day: date) -> str:
    """The seller who doesn't work that day (in turn; never the star)."""
    return IDLE_TURN[day.toordinal() % len(IDLE_TURN)]


def work_day(seller: Any, day: date) -> Any:
    """The seller's day between OPENS and CLOSES, with lunch and the odd unexplained gap;
    None for the day's idle seller (and the rare day off)."""
    rng = gen.rng_for(FEED, "day", seller.alias, day)
    if day.weekday() not in DAYS or seller.alias == idle_on(day) or rng.random() < 0.02:
        return None
    opens = datetime.combine(day, OPENS, tzinfo=IST)
    start = opens + timedelta(minutes=max(0.0, seller.late + rng.gauss(0, 6)))
    end = datetime.combine(day, CLOSES, tzinfo=IST) - timedelta(minutes=rng.uniform(1, 20))
    lunch_start = datetime.combine(day, time(13, 15), tzinfo=IST) + timedelta(
        minutes=rng.uniform(0, 35)
    )
    lunch = (lunch_start, lunch_start + timedelta(minutes=rng.uniform(35, 55)))
    gaps: list[tuple[datetime, datetime]] = []
    if rng.random() < seller.gaps:
        for _ in range(1 if rng.random() < 0.7 else 2):
            length = timedelta(minutes=rng.uniform(50, 110))
            for _attempt in range(20):
                begins = datetime.combine(day, time(10, 30), tzinfo=IST) + timedelta(
                    minutes=rng.uniform(0, 420)
                )
                window = (begins, begins + length)
                clear = all(
                    window[1] + timedelta(minutes=20) <= other[0]
                    or window[0] >= other[1] + timedelta(minutes=20)
                    for other in (lunch, *gaps)
                )
                if clear and window[1] < end - timedelta(minutes=30):
                    gaps.append(window)
                    break
    utc = UTC
    return gen.Shape(
        start.astimezone(utc),
        end.astimezone(utc),
        (lunch[0].astimezone(utc), lunch[1].astimezone(utc)),
        tuple((a.astimezone(utc), b.astimezone(utc)) for a, b in sorted(gaps)),
    )


def night_day(seller: Any, day: date, until: datetime) -> Any:
    """The one-off night batch: the seller's day squeezed between midnight and now, no lunch."""
    if seller.alias == idle_on(day):
        return None
    start = at(day, time(0, 0)) + timedelta(minutes=4 + seller.late / 5)
    earlier = start - timedelta(hours=2)
    return gen.Shape(
        start, until + timedelta(hours=1), (earlier, earlier + timedelta(minutes=1)), ()
    )


def arrival_plan(day: date) -> list[tuple[int, datetime, Any, bool]]:
    """The day's Inbound enquiries, the same on every tick: (number, when, source, a
    repeat). Ads run all day, most in the evening (the generator's hour weights)."""
    rng = gen.rng_for(FEED, "arrivals", day)
    count = rng.randint(*ARRIVALS)
    moments = sorted(
        datetime.combine(
            day,
            time(rng.choices(range(24), gen.HOURS)[0], rng.randrange(60), rng.randrange(60)),
            tzinfo=IST,
        ).astimezone(UTC)
        for _ in range(count)
    )
    sources = gen.ORGS["ac"].sources
    return [
        (number, moment, gen.pick(rng, [(s, s.weight) for s in sources]), rng.random() < 0.03)
        for number, moment in enumerate(moments)
    ]


def support_plan(day: date) -> list[datetime]:
    """When customers ring in with a question that day (working hours)."""
    rng = gen.rng_for(FEED, "support", day)
    return sorted(
        at(day, time(rng.randint(10, 18), rng.randrange(60), rng.randrange(60)))
        for _ in range(rng.randint(*SUPPORT_CALLS))
    )


def alias_of(email: str | None) -> str | None:
    """'ac.priya' from admin+ac.priya@…; None for anyone else."""
    if not email or "+" not in email.split("@", 1)[0]:
        return None
    return email.split("@", 1)[0].split("+", 1)[1].lower()


def phase_of(stage: str, step: str | None, steps: dict[str, str]) -> str | None:
    """What the simulation calls a lead's place: by its stage step, else its desk stage."""
    if step and step in steps:
        return steps[step]
    return BY_STAGE.get(stage)


def fictional_number(phone: str | None) -> int | None:
    """The n of +91 00000 1nnnn (AC's fictional numbers), or None."""
    digits = re.sub(r"\D", "", phone or "")
    if not FICTIONAL.match("+" + digits):
        return None
    return int(digits[-5:]) - gen.ORGS["ac"].phones


def windows(cursor: datetime, until: datetime) -> list[date]:
    """The India days a window touches."""
    first, last = cursor.astimezone(IST).date(), until.astimezone(IST).date()
    return [first + timedelta(days=n) for n in range((last - first).days + 1)]


# ----- the play: the app's own code ---------------------------------------------------------


class FeedRun(gen.Run):
    """The generator's simulation, played over one window (cursor, until] from the sandbox's
    stored state instead of from an empty organisation."""

    def __init__(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        people: dict[str, Any],
        sellers: list[Any],
        profiles: list[Any],
        keys: dict[str, str],
        *,
        cursor: datetime,
        until: datetime,
        real_now: datetime,
        night: bool = False,
        pace: float = 1.0,
    ) -> None:
        if night and pace != 1:
            profiles = [p._replace(think=p.think / pace) for p in profiles]
        spec = gen.ORGS["ac"]._replace(sellers=tuple(profiles), daily=ARRIVALS)
        base = uuid5(FEED, f"{tenant_id}:{cursor.isoformat()}>{until.isoformat()}")
        super().__init__(
            db,
            spec,
            tenant_id,
            base,
            people,
            sellers,
            keys,
            first=cursor.astimezone(IST).date(),
            days=len(windows(cursor, until)),
            until=until,
            scale=1.0,
            test_data=True,
            cold_column=True,
        )
        self.cursor = cursor
        self.real_now = real_now
        self.night = night
        self.free: dict[int, datetime] = {}
        self.unworked: Counter[int] = Counter()  # untouched Cold leads, per seller
        # Every open call-back or send-file task per lead: (task, its holder's index).
        self.open_tasks: dict[UUID, list[tuple[UUID, int | None]]] = {}

    # -- state from the database --------------------------------------------------------

    async def load(self) -> None:
        db, tenant = self.db, self.tenant_id
        steps = {key: name for name, key in self.keys.items()}
        seller_of = {who.person_id: index for index, who in enumerate(self.sellers)}
        talks: Counter[UUID] = Counter()
        misses: Counter[UUID] = Counter()
        for lead_id, data in (
            await db.execute(
                select(LeadEvent.lead_id, LeadEvent.data).where(
                    LeadEvent.tenant_id == tenant, LeadEvent.kind == "result"
                )
            )
        ).all():
            if isinstance(data, dict) and data.get("connected") is True:
                talks[lead_id] += 1
            elif isinstance(data, dict) and data.get("connected") is False:
                misses[lead_id] += 1
        open_tasks: dict[UUID, UUID] = {}
        for task in (
            await db.scalars(
                select(LeadTask)
                .where(LeadTask.tenant_id == tenant, LeadTask.status == "open")
                .order_by(LeadTask.starts_at)
            )
        ).all():
            index = seller_of.get(task.owner_person_id)
            if task.kind == "whatsapp" and index is not None:
                self.whatsapp[index].append(task.id)
            else:
                self.open_tasks.setdefault(task.lead_id, []).append((task.id, index))
                if task.kind == "call_back":
                    open_tasks[task.lead_id] = task.id
        for lead in (
            await db.scalars(select(Lead).where(Lead.tenant_id == tenant, worked()))
        ).all():
            self.used_names.add(lead.name or "")
            number = fictional_number(lead.phone)
            if number is not None:
                self.phone_count = max(self.phone_count, number)
            owner = seller_of.get(lead.owner_person_id)
            phase = phase_of(lead.stage, lead.step, steps)
            if owner is None or phase is None or number is None:
                continue  # not a seller's, or a lead the sandbox didn't make: left alone
            held = self.keep(lead, owner, cold=lead.pipeline == "cold")
            held.phase = phase
            held.talks = talks[lead.id]
            held.misses = misses[lead.id]
            held.task = open_tasks.get(lead.id)
            limit = 2 if held.cold else 6
            held.parked = phase == "nc" and held.misses >= limit
            if held.cold and phase == "new":
                self.unworked[owner] += 1
        # Cold calls each seller made today already count toward their daily cap.
        day_start = at(self.until.astimezone(IST).date(), time(0, 0))
        for actor, lead_id in (
            await db.execute(
                select(LeadEvent.actor_person_id, LeadEvent.lead_id).where(
                    LeadEvent.tenant_id == tenant,
                    LeadEvent.kind == "call",
                    LeadEvent.created_at >= day_start,
                )
            )
        ).all():
            index = seller_of.get(actor)
            held = self.by_id.get(lead_id)
            if index is not None and held is not None and held.cold:
                self.cold_today[(index, self.until.astimezone(IST).date())] += 1
        # Where each seller stopped: their last write (a call's answer can end after a
        # tick's end).
        for actor, last in (
            await db.execute(
                select(LeadEvent.actor_person_id, func.max(LeadEvent.created_at))
                .where(LeadEvent.tenant_id == tenant, LeadEvent.actor_person_id.in_(seller_of))
                .group_by(LeadEvent.actor_person_id)
            )
        ).all():
            self.free[seller_of[actor]] = last + timedelta(minutes=1)

    # -- the generator's hooks, for the feed ---------------------------------------------

    def shape(self, index: int, day: date) -> Any:
        found = (index, day)
        if found not in self.shapes:
            seller = self.spec.sellers[index]
            self.shapes[found] = (
                night_day(seller, day, self.until) if self.night else work_day(seller, day)
            )
        return self.shapes[found]

    async def call(self, index: int, held: Any, moment: datetime) -> datetime:
        """The generator's call, from this seller's own phone, never ending after now, and
        now and then a note on the lead after a real talk."""
        rng = self.rng
        seller = self.spec.sellers[index]
        who = self.sellers[index]
        lead = held.lead
        phase = held.phase
        chance = {
            "new": 0.24 if held.cold else 0.38,
            "nc": 0.18 if held.cold else 0.25,
            "open": 0.4,
            "int": 0.42,
            "done": 0.5,
        }[phase]
        connected = rng.random() < min(0.95, chance * seller.connect)
        outcome = "nc"
        if connected:
            outcome = self.outcome(held)
        if outcome == "open" and "open" not in self.keys:
            outcome = "int"
        seconds = gen.talk_seconds(rng, outcome, seller.talk) if connected else 0
        # Never past now: the answer comes a minute or two after the call ends.
        room = int((self.real_now - moment).total_seconds()) - 200
        if connected and seconds > room:
            seconds = max(8, room)
        ring = timedelta(seconds=rng.uniform(18, 40)) if not connected else timedelta(0)
        ended = moment + timedelta(seconds=seconds) + ring
        logged = await self.desk(
            who, ended + timedelta(seconds=rng.uniform(30, 90))
        ).log_phone_calls(
            PhoneLog(
                device_id=uuid5(FEED, f"phone:{seller.alias}"),
                calls=(
                    PhoneLogCall(
                        log_id=f"feed{int(moment.timestamp())}",
                        number=lead.phone or "",
                        started_at=moment,
                        duration_seconds=seconds,
                        direction="outgoing",
                    ),
                ),
            )
        )
        if logged.logged == 0:
            # The app didn't take the row (a duplicate, or outside its hours): no call, so no
            # answer either (an answer without a call of its own is no call).
            self.counter["calls_not_logged"] += 1
            return ended
        self.counter["calls"] += 1
        self.counter["connected" if connected else "not_connected"] += 1
        self.counter["talk_seconds"] += seconds
        answered = ended + timedelta(seconds=rng.uniform(15, 75))
        desk = self.desk(who, answered)
        old_task = held.task
        if not connected:
            await self.not_connected(index, held, desk, answered)
        else:
            await self.connected(index, held, desk, answered, outcome)
            if held.phase not in ("lost", "junk") and rng.random() < NOTE_SHARE:
                await desk.note(
                    lead.id,
                    NoteCommand(
                        command_id=self.key("note", lead.id, answered.isoformat()),
                        note=rng.choice(NOTES),
                    ),
                )
                self.counter["notes"] += 1
        if old_task is not None and old_task != held.task:
            await self.finish(index, old_task, answered)
        # The call settles the seller's other open tasks on this lead too.
        await self.close_tasks(index, lead.id, held.task, answered)
        return answered

    async def close_tasks(
        self, index: int, lead_id: UUID, keep: UUID | None, moment: datetime
    ) -> None:
        """Mark done the seller's open tasks on a lead, all but ``keep`` (the one just set)."""
        left: list[tuple[UUID, int | None]] = []
        for task_id, holder in self.open_tasks.pop(lead_id, []):
            if task_id == keep or holder != index:
                left.append((task_id, holder))
            else:
                await self.finish(index, task_id, moment)
        if keep is not None and all(task_id != keep for task_id, _ in left):
            left.append((keep, index))
        if left:
            self.open_tasks[lead_id] = left

    def outcome(self, held: Any) -> str:
        """What a real talk led to (the generator's tables)."""
        phase, rng = held.phase, self.rng
        if phase in ("new", "nc"):
            table = (
                (("int", 10), ("open", 12), ("meet", 2), ("lost", 56), ("junk", 14), ("later", 6))
                if held.cold
                else (
                    ("int", 30),
                    ("open", 16),
                    ("meet", 5),
                    ("lost", 33),
                    ("junk", 8),
                    ("later", 8),
                )
            )
        elif phase == "open":
            table = (
                (("int", 33), ("again", 38), ("meet", 7), ("lost", 22))
                if held.talks < 4
                else (("int", 30), ("lost", 70))
            )
        elif phase == "int":
            table = (
                (("meet", 15), ("again", 45), ("lost", 27), ("later", 10), ("won", 3))
                if held.talks < 4
                else (("meet", 15), ("won", 5), ("lost", 80))
            )
        else:
            table = (
                (("won", 16), ("again", 48), ("lost", 36))
                if held.talks < 3
                else (("won", 12), ("lost", 88))
            )
        return str(gen.pick(rng, table))

    async def arrive_one(self, moment: datetime, number: int, source: Any, again: bool) -> None:
        """An enquiry from an ad or the website, given out by the team's rules."""
        day = moment.astimezone(IST).date()
        if again and self.held:
            inbound = [h for h in self.held if not h.cold]
            earlier = self.rng.choice(inbound or self.held)
            record = {
                "name": earlier.lead.name,
                "phone": earlier.lead.phone,
                "interest": earlier.lead.interest,
            }
        else:
            record = self.record(cold=None)
        owner = self.people["owner"]
        lead, outcome = await self.desk(owner, moment).ingest(
            record,
            source=source.source,
            source_label=source.label,
            source_ref=f"feed-{day.isoformat()}-{number}",
            assign="rules",
            actor=None,
            test_data=True,
            command_id=uuid5(FEED, f"arrive:{self.tenant_id}:{day.isoformat()}:{number}"),
            received_at=moment,
        )
        self.counter["arrivals"] += 1
        self.counter[f"live_{outcome}"] += 1
        if outcome != "created" or lead is None:
            return
        index = self.owner_index(lead)
        if index is None:
            self.counter["live_unassigned"] += 1
            return
        self.keep(lead, index, cold=False)

    def cold_team(self) -> list[int]:
        return [i for i, s in enumerate(self.spec.sellers) if s.sides != "inbound"]

    def running_low(self) -> list[int]:
        return [i for i in self.cold_team() if self.unworked[i] < COLD_LOW]

    async def upload_cold(self, moment: datetime) -> None:
        """The coach uploads a fresh Cold list, shared out to the sellers running low."""
        team = self.running_low()
        if not team:
            return
        day = moment.astimezone(IST).date()
        coach = self.people["admin"]
        label = f"File: Business owners, Pune, {day:%d %b}.xlsx"
        desk = self.desk(coach, moment)
        stamp = moment.astimezone(IST).strftime("%H%M")
        for row in range(COLD_BATCH):
            record = self.record(cold=gen.ColdList(label, COLD_BATCH, 0, "Business owners, Pune"))
            index = team[row % len(team)]
            lead, outcome = await desk.ingest(
                record,
                source="csv",
                source_label=label,
                source_ref=f"feed-cold-{day.isoformat()}-{stamp}-{row}",
                assign="person",
                person_id=self.sellers[index].person_id,
                actor=coach.person_id,
                test_data=True,
                command_id=uuid5(FEED, f"cold:{self.tenant_id}:{day.isoformat()}:{stamp}:{row}"),
            )
            self.counter[f"cold_{outcome}"] += 1
            if outcome == "created" and lead is not None:
                lead.pipeline = "cold"
                self.keep(lead, index, cold=True)
                self.unworked[index] += 1

    async def tidy(self, moment: datetime, index: int) -> None:
        """The seller closes their stale Not Connected leads as Lost, no response (the
        after-call sheet's own stage move), so To Call doesn't open on weeks-old lates."""
        stale = [
            h
            for h in self.by_seller[index]
            if h.phase == "nc"
            and (
                h.parked
                or (
                    h.lead.next_action_at is not None
                    and h.lead.next_action_at < moment - STALE_AFTER
                )
            )
        ]
        stale.sort(key=lambda h: h.lead.next_action_at or h.lead.created_at)
        for step, held in enumerate(stale[:TIDY_PER_DAY]):
            lead = held.lead
            await self.desk(self.sellers[index], moment + timedelta(seconds=20 * step)).move(
                lead.id,
                StageMove(
                    command_id=self.key("tidy", lead.id),
                    expected_revision=lead.revision,
                    step=self.keys["lost"],
                    outcome_reason="no_response",
                    via="sheet",
                ),
            )
            held.phase = "lost"
            self.counter["lost_no_response_tidy"] += 1
        # Tasks left open on leads that are closed or gone to History: most sellers clear
        # them; one who skips follow-ups (Farah) mostly doesn't.
        seller = self.spec.sellers[index]
        rng = gen.rng_for(FEED, "tidy-tasks", index, moment.isoformat())
        cleared = 0
        for lead_id, tasks in list(self.open_tasks.items()):
            held = self.by_id.get(lead_id)
            if held is not None and held.phase not in ("won", "lost", "junk"):
                continue
            mine = [task_id for task_id, holder in tasks if holder == index]
            if not mine or rng.random() < seller.skip:
                continue
            await self.close_tasks(index, lead_id, None, moment + timedelta(minutes=5))
            cleared += len(mine)
            if cleared >= 80:
                break
        self.counter["tasks_cleared_tidy"] += cleared

    async def handover(self, moment: datetime, owner: int) -> None:
        """The coach hands the owner one or two hot leads to close (Leads, Move to)."""
        book = [h for h in self.by_seller[owner] if h.phase not in ("won", "lost", "junk")]
        room = OWNER_BOOK - len(book)
        if room <= 0:
            return
        rng = gen.rng_for(FEED, "handover", moment.isoformat())
        hot = [
            h
            for index, mine in enumerate(self.by_seller)
            if index != owner
            for h in mine
            if h.phase in ("done", "int") and not h.cold and h.lead.created_at < moment
        ]
        hot.sort(key=lambda h: (h.phase != "done", -h.talks))
        for step, held in enumerate(hot[: min(room, rng.randint(*HANDOVER))]):
            lead = held.lead
            await self.desk(self.people["admin"], moment + timedelta(seconds=30 * step)).reassign(
                lead.id,
                Reassign(
                    command_id=self.key("handover", lead.id),
                    expected_revision=lead.revision,
                    person_id=self.sellers[owner].person_id,
                ),
            )
            self.by_seller[held.owner].remove(held)
            held.owner = owner
            self.by_seller[owner].append(held)
            self.counter["handed_to_owner"] += 1
            await self.owner_today(owner, held, moment + timedelta(minutes=2 + step), rng)

    async def owner_today(self, owner: int, held: Any, moment: datetime, rng: Any) -> None:
        """The owner books himself a call on the lead later today (a follow-up and its
        call-back task), so his Me view has work due today."""
        day = moment.astimezone(IST).date()
        if self.night:
            due = moment + timedelta(minutes=rng.uniform(20, 60))
        else:
            due = max(at(day, time(14, 0)), moment + timedelta(minutes=45)) + timedelta(
                minutes=rng.choice((0, 30, 60, 90, 120))
            )
            if due > at(day, time(18, 30)):
                return
        lead = held.lead
        await self.desk(self.sellers[owner], moment).follow_up(
            lead.id,
            FollowUp(
                command_id=self.key("owner-follow-up", lead.id),
                expected_revision=lead.revision,
                at=due,
            ),
        )
        held.task = await self.task(owner, held, moment, "call_back", due)
        self.open_tasks.setdefault(lead.id, []).append((held.task, owner))
        self.counter["owner_follow_ups"] += 1

    async def support(self, moment: datetime, number: int) -> None:
        """A customer who already bought rings their seller with a question: a call that
        isn't a sale, with a note saying so."""
        rng = gen.rng_for(FEED, "support-call", moment.isoformat(), number)
        customers = [
            h
            for h in self.held
            if h.phase in ("won", "done")
            and self.window_at(h.owner, moment) == moment
            and h.lead.created_at < moment
        ]
        if not customers:
            return
        held = rng.choice(customers)
        who = self.sellers[held.owner]
        seconds = rng.randint(70, 320)
        ended = moment + timedelta(seconds=seconds)
        if ended + timedelta(minutes=3) > self.real_now:
            return
        seller = self.spec.sellers[held.owner]
        logged = await self.desk(who, ended + timedelta(seconds=40)).log_phone_calls(
            PhoneLog(
                device_id=uuid5(FEED, f"phone:{seller.alias}"),
                calls=(
                    PhoneLogCall(
                        log_id=f"feedin{int(moment.timestamp())}",
                        number=held.lead.phone or "",
                        started_at=moment,
                        duration_seconds=seconds,
                        direction="incoming",
                    ),
                ),
            )
        )
        if logged.logged == 0:
            return
        await self.desk(who, ended + timedelta(seconds=90)).note(
            held.lead.id,
            NoteCommand(
                command_id=self.key("support", held.lead.id, moment.isoformat()),
                note=rng.choice(SUPPORT_NOTES),
            ),
        )
        self.busy[held.owner].append((moment, ended + timedelta(minutes=2)))
        self.counter["support_calls"] += 1
        self.counter["talk_seconds"] += seconds

    # -- the window ------------------------------------------------------------------------

    async def play(self) -> None:
        cursor, until = self.cursor, self.until
        for day in windows(cursor, until):
            for number, moment, source, again in arrival_plan(day):
                if cursor < moment <= until:
                    self.push(moment, "arrive", (number, source, again))
            topup = cursor + timedelta(minutes=3) if self.night else at(day, time(11, 20))
            if cursor < topup <= until and self.running_low():
                self.push(topup, "cold", None)
            for number, moment in enumerate(support_plan(day)):
                if cursor < moment <= until and not self.night:
                    self.push(moment, "support", number)
            for index in range(len(self.sellers)):
                shape = self.shape(index, day)
                if shape is None:
                    continue
                tidy_at = (cursor if self.night else shape.start) + timedelta(minutes=1)
                if cursor < tidy_at <= until and self.sellers[index].role == "member":
                    self.push(tidy_at, "tidy", index)
                if self.sellers[index].role == "owner":
                    handover = cursor + timedelta(minutes=2) if self.night else at(day, time(12, 5))
                    if cursor < handover <= until:
                        self.push(handover, "handover", index)
                # A seller picks up a moment after the window opens, never on its edge.
                resume = cursor + timedelta(seconds=self.rng.uniform(20, 120))
                start = max(shape.start, resume, self.free.get(index, cursor))
                if start < min(until, shape.end):
                    self.push(start, "seller", index)
        # Meetings whose time has passed: held, missed or moved off (one left from before
        # the window is closed early in it).
        for row in (
            await self.db.scalars(
                select(LeadMeeting).where(
                    LeadMeeting.tenant_id == self.tenant_id, LeadMeeting.status == "scheduled"
                )
            )
        ).all():
            held = self.by_id.get(row.lead_id)
            if held is None or held.phase != "meet":
                continue
            ends = row.starts_at + timedelta(minutes=row.duration_minutes)
            moment = ends + timedelta(minutes=self.rng.uniform(5, 40))
            if moment <= cursor:
                moment = cursor + timedelta(minutes=self.rng.uniform(2, 30))
            self.push(moment, "meeting", row.lead_id)
        while self.queue:
            moment, _, kind, payload = gen.heapq.heappop(self.queue)
            if moment > until:
                break
            if kind == "arrive":
                await self.arrive_one(moment, *payload)
            elif kind == "cold":
                await self.upload_cold(moment)
            elif kind == "support":
                await self.support(moment, payload)
            elif kind == "tidy":
                await self.tidy(moment, payload)
            elif kind == "handover":
                await self.handover(moment, payload)
            elif kind == "seller":
                await self.turn(moment, payload)
            elif kind == "meeting":
                await self.meeting(moment, payload)
        await self.db.flush()


# ----- the workspace --------------------------------------------------------------------


class Workspace(NamedTuple):
    tenant_id: UUID
    people: dict[str, Any]
    sellers: list[Any]
    profiles: list[Any]
    keys: dict[str, str]


async def workspace(db: AsyncSession, tenant_id: UUID, environment: str) -> Workspace:
    """The sandbox, checked: dev only, flagged as a sandbox, the right name."""
    if environment != "development":
        raise Refused("not_development", environment=environment)
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None or tenant.name != NAME:
        raise Refused("not_the_sandbox")
    if await db.get(ConversationSandboxOrganisation, tenant_id) is None:
        raise Refused("not_flagged_as_sandbox")
    members = (
        await db.execute(
            select(Membership.role, Person.id, Person.email, Person.display_name)
            .join(Person, Person.id == Membership.person_id)
            .where(Membership.tenant_id == tenant_id, Membership.ended_at.is_(None))
        )
    ).all()
    owner = next(((pid, name) for role, pid, _, name in members if role == "owner"), None)
    coach = next(
        (
            (pid, name)
            for role, pid, email, name in members
            if role == "admin" and (email or "").lower().startswith("dipak@")
        ),
        None,
    ) or next(((pid, name) for role, pid, _, name in members if role == "admin"), None)
    if owner is None or coach is None:
        raise Refused("owner_or_coach_missing")
    people = {
        "owner": gen.Actor(owner[0], "owner", owner[1] or "Owner"),
        "admin": gen.Actor(coach[0], "admin", coach[1] or "Coach"),
    }
    sellers, profiles = [], []
    for role, pid, email, name in sorted(members, key=lambda m: alias_of(m[2]) or ""):
        alias = alias_of(email)
        if role != "member" or alias is None:
            continue
        sellers.append(gen.Actor(pid, "member", name or alias))
        profiles.append(PROFILES.get(alias, DEFAULT_PROFILE._replace(alias=alias)))
    if not sellers:
        raise Refused("no_sellers")
    # The owner last: he closes the leads the coach hands him (OWNER_PROFILE).
    sellers.append(people["owner"])
    profiles.append(OWNER_PROFILE)
    return Workspace(tenant_id, people, sellers, profiles, await gen._keys(db, tenant_id))


async def cursor_of(db: AsyncSession, tenant_id: UUID) -> datetime | None:
    payload = await db.scalar(
        select(AuditEvent.payload)
        .where(AuditEvent.tenant_id == tenant_id, AuditEvent.action == ACTION)
        .order_by(AuditEvent.sequence_no.desc())
        .limit(1)
    )
    if isinstance(payload, dict) and payload.get("until"):
        return datetime.fromisoformat(str(payload["until"]))
    return None


async def last_activity(db: AsyncSession, tenant_id: UUID) -> datetime | None:
    found: datetime | None = await db.scalar(
        select(func.max(LeadEvent.created_at)).where(LeadEvent.tenant_id == tenant_id)
    )
    return found


async def hours(db: AsyncSession, ws: Workspace, now: datetime, *, all_day: bool) -> None:
    """The team's work hours: every day 09:30 to 19:30 with lunch, or (the night batch,
    inside its own transaction only) the whole day."""
    desk = gen.Run.desk(_Bare(db, ws.tenant_id), ws.people["owner"], now)
    revision, _ = await desk.settings()
    await desk.save_work_hours(
        WorkHoursCommand(
            expected_revision=revision,
            days=DAYS,
            start="00:00" if all_day else OPENS.strftime("%H:%M"),
            end="23:59" if all_day else CLOSES.strftime("%H:%M"),
            pause_leads=False,
            breaks=()
            if all_day
            else ({"start": LUNCH[0].strftime("%H:%M"), "end": LUNCH[1].strftime("%H:%M")},),
        )
    )


class _Bare:
    """Just enough of a Run for gen.Run.desk()."""

    def __init__(self, db: AsyncSession, tenant_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id


async def archive(db: AsyncSession, ws: Workspace, now: datetime) -> Counter[str]:
    """The rolling window: leads closed more than ARCHIVE_AFTER ago, and leads typed in by
    hand (testers' and the QA robot's, 1 Nov: neither the generator nor the feed types a
    lead), move to History: kept, counted in Analytics, out of every work list. Never
    deleted."""
    moved: Counter[str] = Counter()
    for lead in (
        await db.scalars(select(Lead).where(Lead.tenant_id == ws.tenant_id, worked()))
    ).all():
        closed_long_ago = (
            lead.stage in ("won", "lost", "junk")
            and (lead.stage_at or lead.updated_at) < now - ARCHIVE_AFTER
        )
        typed_in = lead.source == "manual"
        if closed_long_ago or typed_in:
            lead.pipeline = HISTORY
            lead.updated_at = now
            moved["typed_in" if typed_in else "closed"] += 1
    await db.flush()
    return moved


async def newcomer(
    db: AsyncSession, ws: Workspace, now: datetime, boundaries: tuple[UUID, UUID]
) -> str:
    """The sixth seller (a long name), a Member who takes new enquiries; no password, so
    nobody signs in as them."""
    from ac_platform.organisations.service import OrganisationService

    first, last, alias = NEWCOMER
    local, domain = MAILBOX.split("@", 1)
    email = f"{local}+{alias}@{domain}"
    person = await db.scalar(select(Person).where(func.lower(Person.email) == email))
    made = "found"
    if person is None:
        person_id = uuid5(FEED, f"person:{email}")
        await AsyncSqlAlchemyIdentityRepository(db).save_person(
            PersonSnapshot(
                id=person_id, email=email, display_name=f"{first} {last}", email_verified_at=now
            )
        )
        await db.flush()
        made = "made"
    else:
        person_id = person.id
    member = await db.scalar(
        select(Membership).where(
            Membership.tenant_id == ws.tenant_id,
            Membership.person_id == person_id,
            Membership.ended_at.is_(None),
        )
    )
    if member is None:
        service = OrganisationService(
            db, operations_tenant_id=boundaries[0], public_learner_tenant_id=boundaries[1]
        )
        await service.add_member(
            ws.tenant_id,
            person_id,
            "member",
            uuid5(FEED, f"member:{ws.tenant_id}:{person_id}"),
            operator_reference="dev sandbox feed (owner, 15 Nov 2026)",
            reason="Fictional seller for the dev sandbox",
        )
        await db.flush()
        made += "+joined"
    row = await db.get(LeadRep, (ws.tenant_id, person_id))
    desk = gen.Run.desk(_Bare(db, ws.tenant_id), ws.people["owner"], now)
    await desk.save_rep(
        person_id,
        RepRules(expected_revision=row.revision if row else 0, available=True, max_open=None),
    )
    return made


async def avatars(db: AsyncSession, ws: Workspace) -> int:
    """A drawn portrait for each seller without a photo (never a real person's)."""
    from ac_platform.identity import person_photos

    portraits = _avatars_module()
    done = 0
    for who, profile in zip(ws.sellers, ws.profiles, strict=True):
        if who.role != "member" or await db.get(PersonPhoto, who.person_id) is not None:
            continue  # never the owner's own picture
        await person_photos.save_upload(
            db,
            person_id=who.person_id,
            session_id=None,
            tenant_id=ws.tenant_id,
            content_type="image/png",
            data=portraits.portrait(profile.alias),
        )
        done += 1
    return done


def _avatars_module() -> ModuleType:
    path = HERE / "avatars.py"
    loader = importlib.util.spec_from_file_location("sandbox_feed_avatars", path)
    assert loader is not None and loader.loader is not None
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    return module


# ----- the commands -----------------------------------------------------------------------


async def record(
    db: AsyncSession, ws: Workspace, mode: str, cursor: datetime, until: datetime, counts: Any
) -> None:
    """The cursor and what was made, as one audit event in the same transaction."""
    await append_audit_event(
        db,
        tenant_id=ws.tenant_id,
        actor_person_id=ws.people["owner"].person_id,
        actor_type="operator",
        action=ACTION,
        resource_type="tenant",
        resource_id=ws.tenant_id,
        request_id=str(uuid5(FEED, f"{mode}:{cursor.isoformat()}>{until.isoformat()}")),
        reason=f"Dev sandbox feed ({mode}): fictional work played up to {until.isoformat()}",
        payload={
            "mode": mode,
            "cursor": cursor.isoformat(),
            "until": until.isoformat(),
            "made": dict(sorted(counts.items())),
        },
    )


async def play_window(
    db: AsyncSession,
    ws: Workspace,
    mode: str,
    cursor: datetime,
    until: datetime,
    real_now: datetime,
    *,
    night: bool = False,
    pace: float = 1.0,
) -> dict[str, Any]:
    run = FeedRun(
        db,
        ws.tenant_id,
        ws.people,
        ws.sellers,
        ws.profiles,
        ws.keys,
        cursor=cursor,
        until=until,
        real_now=real_now,
        night=night,
        pace=pace,
    )
    await run.load()
    await run.play()
    counts = {k: v for k, v in run.counter.items() if k != "commands"}
    await record(db, ws, mode, cursor, until, counts)
    return {
        "mode": mode,
        "cursor": cursor.isoformat(),
        "until": until.isoformat(),
        "idle_today": idle_on(until.astimezone(IST).date()),
        "made": dict(sorted(counts.items())),
    }


async def today(db: AsyncSession, ws: Workspace, now: datetime) -> dict[str, Any]:
    """Today's numbers from what the app stored, per seller: calls the phone logged,
    connected (phone seconds), talk time, open and overdue tasks; new leads today."""
    start = at(now.astimezone(IST).date(), time(0, 0))
    names = {who.person_id: who.name for who in ws.sellers}
    per: dict[str, Counter[str]] = {name: Counter() for name in names.values()}
    for actor, data in (
        await db.execute(
            select(LeadEvent.actor_person_id, LeadEvent.data).where(
                LeadEvent.tenant_id == ws.tenant_id,
                LeadEvent.kind == "call",
                LeadEvent.created_at >= start,
            )
        )
    ).all():
        if actor not in names or not counted_phone_call(data):
            continue
        tally = per[names[actor]]
        seconds = int((data or {}).get("duration_seconds") or 0)
        tally["calls"] += 1
        tally["connected"] += seconds > 0
        tally["talk_seconds"] += seconds
    for person, due in (
        await db.execute(
            select(LeadTask.owner_person_id, LeadTask.starts_at).where(
                LeadTask.tenant_id == ws.tenant_id, LeadTask.status == "open"
            )
        )
    ).all():
        if person in names:
            per[names[person]]["tasks_open"] += 1
            per[names[person]]["tasks_overdue"] += due < now
    new_today = await db.scalar(
        select(func.count()).where(
            Lead.tenant_id == ws.tenant_id, Lead.created_at >= start, worked(), Lead.source != "csv"
        )
    )
    total = Counter[str]()
    for tally in per.values():
        total.update(tally)
    return {
        "day": now.astimezone(IST).date().isoformat(),
        "new_inbound_today": int(new_today or 0),
        "team": dict(total),
        "sellers": {name: dict(tally) for name, tally in per.items()},
    }


async def run(
    sessions: async_sessionmaker[AsyncSession],
    command: str,
    *,
    apply: bool,
    now: datetime,
    tenant_id: UUID = TENANT,
    environment: str,
    boundaries: tuple[UUID, UUID] | None = None,
    pace: float = 3.0,
    with_avatars: bool = True,
    since: date | None = None,
) -> list[dict[str, Any]]:
    """One command, each window in its own transaction (committed with apply)."""
    reports: list[dict[str, Any]] = []

    async def once(work: Any) -> dict[str, Any] | None:
        async with sessions() as db:
            try:
                if command == "read":
                    from sqlalchemy import text

                    await db.execute(text("SET TRANSACTION READ ONLY"))
                ws = await workspace(db, tenant_id, environment)
                report = await work(db, ws)
            except BaseException:
                await db.rollback()
                raise
            if apply and command != "read":
                await db.commit()
            else:
                await db.rollback()
        if report is not None:
            report["applied"] = apply and command != "read"
            reports.append(report)
        return report

    if command == "read":

        async def read(db: AsyncSession, ws: Workspace) -> dict[str, Any]:
            return {
                "cursor": (c.isoformat() if (c := await cursor_of(db, ws.tenant_id)) else None),
                "today": await today(db, ws, now),
            }

        await once(read)
        return reports

    if command == "setup":

        async def setup(db: AsyncSession, ws: Workspace) -> dict[str, Any]:
            if boundaries is None:
                raise Refused("tenant_boundaries_not_configured")
            seller = await newcomer(db, ws, now, boundaries)
            await hours(db, ws, now, all_day=False)
            moved = await archive(db, ws, now)
            ws = await workspace(db, ws.tenant_id, environment)
            drawn = await avatars(db, ws) if (apply and with_avatars) else 0
            return {
                "mode": "setup",
                "newcomer": seller,
                "work_hours": f"every day {OPENS:%H:%M}-{CLOSES:%H:%M}, lunch break",
                "to_history": dict(moved),
                "avatars_drawn": drawn,
                "sellers": [who.name for who in ws.sellers],
            }

        await once(setup)
        return reports

    if command == "tick":

        async def tick(db: AsyncSession, ws: Workspace) -> dict[str, Any] | None:
            until = now - LAG
            cursor = await cursor_of(db, ws.tenant_id) or await last_activity(db, ws.tenant_id)
            cursor = max(cursor or until - timedelta(minutes=15), until - CATCH_UP)
            if until <= cursor:
                return {"mode": "tick", "nothing_to_play": True, "cursor": cursor.isoformat()}
            report = await play_window(db, ws, "tick", cursor, until, now)
            if cursor.astimezone(IST).date() != until.astimezone(IST).date():
                report["to_history"] = dict(await archive(db, ws, until))
            return report

        await once(tick)
        return reports

    if command == "backfill":
        # Whole days, each its own transaction: from the last activity to the last midnight.
        midnight = at(now.astimezone(IST).date(), time(0, 0))

        async def first_cursor(db: AsyncSession, ws: Workspace) -> dict[str, Any]:
            found = await cursor_of(db, ws.tenant_id)
            if found is None:
                found = at(since, time(0, 0)) if since else await last_activity(db, ws.tenant_id)
            return {"cursor": (found or midnight - timedelta(days=1)).isoformat()}

        async with sessions() as db:
            ws0 = await workspace(db, tenant_id, environment)
            start = datetime.fromisoformat((await first_cursor(db, ws0))["cursor"])
            await db.rollback()
        cursor = start
        while cursor < midnight:
            next_midnight = at(cursor.astimezone(IST).date() + timedelta(days=1), time(0, 0))
            until = min(next_midnight, midnight)
            window = (cursor, until)

            async def day(db: AsyncSession, ws: Workspace, window: Any = window) -> dict[str, Any]:
                report = await play_window(db, ws, "backfill", window[0], window[1], window[1])
                report["to_history"] = dict(await archive(db, ws, window[1]))
                return report

            await once(day)
            if not apply:
                break  # a dry run rehearses the first day only (each day builds on the last)
            cursor = until
        return reports

    if command == "night":

        async def night(db: AsyncSession, ws: Workspace) -> dict[str, Any]:
            midnight = at(now.astimezone(IST).date(), time(0, 0))
            cursor = max(await cursor_of(db, ws.tenant_id) or midnight, midnight)
            until = now - timedelta(minutes=2)
            if until <= cursor:
                return {"mode": "night", "nothing_to_play": True}
            # The phone logs a call only inside work hours: the whole day for this
            # transaction, then the real hours again before it commits.
            await hours(db, ws, cursor, all_day=True)
            report = await play_window(db, ws, "night", cursor, until, now, night=True, pace=pace)
            await hours(db, ws, until, all_day=False)
            return report

        await once(night)
        return reports

    raise Refused("unknown_command", command=command)


async def main(argv: Sequence[str]) -> int:
    flags = {a for a in argv if a.startswith("--")}
    args = [a for a in argv if not a.startswith("--")]
    command = args[0] if args else "read"
    pace = 3.0
    since: date | None = None
    for flag in flags:
        if flag.startswith("--pace="):
            pace = float(flag.split("=", 1)[1])
        if flag.startswith("--from="):
            since = date.fromisoformat(flag.split("=", 1)[1])
    from ac_platform.application.settings import get_settings

    settings = get_settings()
    boundaries = (
        (settings.operations_tenant_id, settings.public_learner_tenant_id)
        if settings.operations_tenant_id and settings.public_learner_tenant_id
        else None
    )
    engine = create_async_engine(settings.database_url, hide_parameters=True, pool_size=2)
    try:
        reports = await run(
            async_sessionmaker(engine, expire_on_commit=False),
            command,
            apply="--apply" in flags,
            now=datetime.now(UTC),
            tenant_id=UUID(os.environ.get("AC_SANDBOX_FEED_TENANT", str(TENANT))),
            environment=str(settings.environment),
            boundaries=boundaries,
            pace=pace,
            since=since,
        )
    finally:
        await engine.dispose()
    print(json.dumps({"command": command, "reports": reports}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
