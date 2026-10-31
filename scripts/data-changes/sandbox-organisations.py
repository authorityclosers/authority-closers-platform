"""Two fictional Sales X-Ray sandbox organisations with 30 days of realistic work, so every
view shows data (approved data change).

Owner, 30 Oct 2026 (owner chat, through the orchestrator): realistic sandbox data so the
owner and the sales coach see every view populated and test as an owner and as a seller,
with a login for each seller (docs/product/lead-desk/stages-views-sources.md, section 7).
For each organisation, in one transaction of its own, through the app's own code:
  1. five fictional sellers' accounts: plus-aliases of the owner's mailbox (so any mail
     reaches it), verified, each with the scrypt verifier of a password given in the input
     (the password itself lives only in Infisical, never here);
  2. the organisation (``OrganisationService.create``), the owner as its Owner, the sales
     coach as an Admin and the sellers as Members; the recommended nine stages (owner and
     Dipak, final, 30 Oct 2026: New Lead / Unworked, Not Connected, Open Leads, Interested,
     Meeting Scheduled, Meeting Done, Won, Closed / Lost, Junk Lead), or the sales team's
     stages where that template is not in the app yet; work hours Monday to Saturday, 10:30
     to 19:00 with lunch set as a break; flagged as a sandbox
     (``conversation_sandbox_organisations``): the Call button simulates and dials nobody,
     and the nightly lake export and product telemetry leave the organisation out
     (``telemetry.sales_xray_consent.read_standing``);
  3. 30 days of work up to now, simulated minute by minute. Inbound Leads: 3 to 10
     enquiries a day from Meta, Google, the website and YouTube, given out by the team's own
     rules. Cold Leads (``pipeline`` "cold", migration 0146): a past list of about 100
     uploaded early and worked through the month, and a list of about 900 uploaded two days
     before the end, nearly all still Unworked. Calls as the seller's phone logs them, with
     their real start and seconds (about 60% not connected), each followed by the
     after-call answer; Open Leads and Interested with follow-ups, call-back tasks and
     reminders, some left overdue; meetings booked, held, missed or cancelled; wins, losses
     and junk with their reasons. A few scripted leads on each side make sure every stage has
     a lead. Sellers work 10:30 to 19:00 with lunch; some have one or two unexplained gaps of
     one to two hours, one joins the team on day 10, and everyone takes the odd day off;
  4. one audit event naming the approver and the issue.
Every lead is test data. Names are made up, every phone number is +91 00000 xxxxx (no such
Indian number exists), every lead email is at example.com, and nothing is sent to anyone.

A dry run (the default) makes the whole change in its transaction, reports it and rolls it
back. ``--apply`` commits, one organisation at a time. A rerun finds each organisation by
its command id and changes nothing. ``--read`` reads the result back in a read-only
transaction. ``--logins`` prints, without touching the database, the sellers' sign-in
emails the input must carry a verifier for.

Run inside the API container with the deployed settings (its filesystem is read-only, so
the input goes inline):
    docker exec -i <api> python - '<input JSON>' [--apply | --read | --logins] \
        < sandbox-organisations.py
input: {"command_id", "approver_email", "issue", "owner_email", "admin_email",
        "seller_mailbox", "organisations": ["ac", "cyber"], "password_hashes": {email: verifier},
        "end"?: "YYYY-MM-DD" (the last day, India time; default today), "days"?: 30,
        "scale"?: 1.0, "test_data"?: true, "require_pipeline"?: true,
        "name_suffix"?: words after each organisation's name (a second build beside a first)}
Prints counts, the organisations' names and the sellers' sign-in emails; never a lead's
details, never a password or a verifier.
"""

from __future__ import annotations

import asyncio
import hashlib
import heapq
import json
import random
import re
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Final, Literal, NamedTuple
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.settings import get_settings
from ac_platform.audit.service import append_audit_event
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
)
from ac_platform.identity.models import PasswordCredential, Person
from ac_platform.identity.repositories import AsyncSqlAlchemyIdentityRepository
from ac_platform.identity.services import PersonSnapshot
from ac_platform.lead_desk import meetings as meeting_rows
from ac_platform.lead_desk import tasks as task_book
from ac_platform.lead_desk.contracts import (
    Disposition,
    MeetingClosed,
    MeetingCommand,
    MeetingDone,
    MeetingInput,
    PhoneLog,
    PhoneLogCall,
    RepRules,
    StageMove,
    TaskAction,
    TaskCommand,
    WorkHoursCommand,
)
from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.journey.templates import TEMPLATES
from ac_platform.lead_desk.models import Lead, LeadEvent, LeadMeeting, LeadRep, LeadTask
from ac_platform.lead_desk.store import LeadDesk, Viewer
from ac_platform.organisations.service import OrganisationService
from ac_platform.product_updates.models import Notification
from ac_platform.tenancy.models import Membership, Organisation, Tenant

Mode = Literal["dry-run", "apply", "read"]
IST: Final = ZoneInfo("Asia/Kolkata")
ACTION: Final = "lead_desk.sandbox_organisation_data_change"
APPROVAL: Final = "owner chat 30 Oct 2026"
WORK_DAYS: Final = (0, 1, 2, 3, 4, 5)  # Monday to Saturday
DAY_START: Final = time(10, 30)
DAY_END: Final = time(19, 0)
LUNCH: Final = (time(13, 30), time(14, 15))
VERIFIER: Final = re.compile(r"\Ascrypt\$ln=15,r=8,p=1\$[A-Za-z0-9_-]{16,}\$[A-Za-z0-9_-]{32,}\Z")
# What each meaning is called in the installed stage list: found by meaning, never by name,
# so a renamed or re-ordered list still works.
MEANINGS: Final = {
    "new": "lead",
    "nc": "unreachable",
    "int": "qualified",
    "meet": "appointment_booked",
    "done": "appointment_done",
    "won": "won",
    "lost": "lost",
}
# In the nine stages only; without them an open talk is Interested and junk is Lost.
OPTIONAL_MEANINGS: Final = {"open": "contacted", "junk": "disqualified"}
RECOMMENDED: Final = "recommended"
# Junk only for a contact confirmed invalid, fake or unusable; never for unanswered calls
# (Dipak's handoff, 31 Oct 2026, section 10B).
JUNK_REASONS: Final = (
    ("invalid_number", 40),
    ("fake", 25),
    ("unusable_contact", 20),
    ("someone_else", 15),
)
# Open Leads always says why it is open (no Half Discussion stage).
OPEN_REASONS: Final = (("Call later", 55), ("Discussion incomplete", 45))
# The handoff's stage order: New Lead / Unworked, Open Leads, Not Connected, Interested, the
# meetings, Won, Closed / Lost, Junk Lead.
ORDER: Final = (
    "lead",
    "contacted",
    "unreachable",
    "qualified",
    "appointment_booked",
    "appointment_done",
    "won",
    "lost",
    "disqualified",
)
# Scripted leads, one per story on each side, so every stage holds a lead at the end. Each
# call takes the next step; the last step repeats. "late": a meeting booked in the last five
# days for a week later (so it is still ahead), a follow-up before that.
STORIES: Final[dict[str, tuple[str, ...]]] = {
    "won": ("meet", "won"),
    "done": ("meet", "again"),
    "meet_late": ("int", "late"),
    "int": ("int", "again"),
    "open": ("open", "again"),
    "lost": ("lost",),
    "junk": ("junk",),
}
NC_REASONS: Final = (
    ("did_not_pick", 50),
    ("busy", 14),
    ("switched_off", 14),
    ("disconnected", 10),
    ("out_of_coverage", 6),
    ("not_in_use", 3),
    ("invalid_number", 3),
)
NO_RETRY: Final = frozenset({"not_in_use", "invalid_number"})
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
FIRST_NAMES: Final = (
    "Aarav",
    "Aditi",
    "Ajay",
    "Akash",
    "Amit",
    "Ananya",
    "Anil",
    "Anjali",
    "Arjun",
    "Ashwini",
    "Bhavna",
    "Chetan",
    "Deepa",
    "Devendra",
    "Divya",
    "Gaurav",
    "Harsh",
    "Isha",
    "Jayesh",
    "Jyoti",
    "Kajal",
    "Kiran",
    "Komal",
    "Kunal",
    "Lalit",
    "Madhuri",
    "Mahesh",
    "Manasi",
    "Manoj",
    "Meera",
    "Mohit",
    "Nandini",
    "Nikhil",
    "Nilesh",
    "Omkar",
    "Pallavi",
    "Pankaj",
    "Prachi",
    "Prasad",
    "Pratik",
    "Rahul",
    "Rajesh",
    "Rashmi",
    "Ritu",
    "Sachin",
    "Sagar",
    "Sakshi",
    "Sameer",
    "Sanjay",
    "Shreya",
    "Shubham",
    "Siddharth",
    "Sonali",
    "Suresh",
    "Swati",
    "Tejas",
    "Tanvi",
    "Umesh",
    "Varun",
    "Vaishali",
    "Vinod",
    "Yash",
    "Zoya",
    "Faisal",
    "Ayesha",
    "Joseph",
    "Mary",
    "Harpreet",
    "Gurpreet",
    "Lakshmi",
    "Venkat",
)
LAST_NAMES: Final = (
    "Patil",
    "Joshi",
    "Kale",
    "Pawar",
    "Jadhav",
    "Shinde",
    "More",
    "Gaikwad",
    "Chavan",
    "Sawant",
    "Bhosale",
    "Kadam",
    "Naik",
    "Salunkhe",
    "Mane",
    "Thakur",
    "Sharma",
    "Verma",
    "Gupta",
    "Agarwal",
    "Mehta",
    "Shah",
    "Desai",
    "Rao",
    "Reddy",
    "Menon",
    "Pillai",
    "Das",
    "Banerjee",
    "Singh",
    "Chauhan",
    "Mishra",
    "Pandey",
    "Tiwari",
    "Khan",
    "Ansari",
    "Sheikh",
    "D'Souza",
    "Fernandes",
    "Gill",
    "Bhatia",
    "Malhotra",
    "Kapoor",
    "Iyer",
    "Nair",
    "Bhagat",
)
# The share of a day's enquiries in each hour (India time): Meta peaks in the evening.
HOURS: Final = (
    (1, 1, 0.5, 0.3, 0.3, 0.5, 1, 2, 3, 4, 4, 4)  # midnight to noon
    + (3.5, 3, 3, 3, 3, 3.5, 4, 5, 5.5, 5, 3.5, 2)  # noon to midnight
)


class Seller(NamedTuple):
    """One fictional seller and how they work. A named tuple: the script also loads as a
    plain file."""

    first: str
    last: str
    city: str
    alias: str  # the mailbox's plus-alias
    late: int  # minutes after 10:30 a usual day starts
    think: float  # mean minutes between calls
    gaps: float  # the share of days with one or two unexplained gaps of 1-2 hours
    skip: float  # the share of due follow-ups left for another day
    cold_cap: int  # cold calls a day, at most
    talk: float  # how long their conversations run (1.0 usual)
    joins: int  # the day they start (0: from the first day)
    connect: float  # how often their calls connect, relative
    # Which leads they work: "both", "inbound" (no cold list) or "cold" (no new enquiries),
    # so the Inbound | Cold selector shows for some sellers and hides for others.
    sides: str = "both"


class Source(NamedTuple):
    source: str  # the lead's source as the app stores it
    label: str
    weight: int
    typed: bool = False  # typed in by a seller (a walk-in or a call)


class ColdList(NamedTuple):
    """A bulk upload to Cold Leads: its file, its rows, the day it came in (from the first
    day; negative: from the last) and what the people on it are."""

    label: str
    size: int
    day: int
    reason: str


class OrgSpec(NamedTuple):
    key: str
    name: str
    sellers: tuple[Seller, ...]
    sources: tuple[Source, ...]
    interests: tuple[str, ...]
    details: tuple[tuple[str, tuple[str, ...]], ...]  # extra form answers
    cities: tuple[str, ...]
    daily: tuple[int, int]  # Inbound enquiries a day, at least and at most
    cold: tuple[ColdList, ...]
    deals: tuple[int, ...]
    meeting: tuple[str, str, str | None, str | None]  # mode, agenda, link, place
    phones: int  # the first fictional number


ORGS: Final[dict[str, OrgSpec]] = {
    "ac": OrgSpec(
        key="ac",
        name="AC Sales Sandbox",
        sellers=(
            Seller("Priya", "Deshmukh", "Pune", "ac.priya", 0, 6.0, 0.04, 0.02, 2, 1.0, 0, 1.15),
            Seller("Rohan", "Patil", "Pune", "ac.rohan", 5, 7.0, 0.06, 0.05, 2, 0.9, 0, 1.0),
            Seller(
                "Sneha",
                "Iyer",
                "Mumbai",
                "ac.sneha",
                10,
                9.0,
                0.08,
                0.06,
                0,
                1.45,
                0,
                1.05,
                "inbound",
            ),
            Seller(
                "Aditya", "Joshi", "Pune", "ac.aditya", 25, 8.0, 0.4, 0.25, 10, 0.85, 0, 0.9, "cold"
            ),
            Seller("Farah", "Shaikh", "Mumbai", "ac.farah", 10, 8.0, 0.18, 0.12, 2, 1.0, 9, 0.85),
        ),
        sources=(
            Source("meta", "Meta Ads: Sales mastery webinar form", 22),
            Source("meta", "Meta Ads: Closer career form", 18),
            Source("webhook", "Google Ads: Sales coaching lead form", 22),
            Source("webhook", "Website: /programme", 12),
            Source("webhook", "Website: /free-masterclass", 8),
            Source("webhook", "YouTube: Closing skills video enquiry", 18),
        ),
        interests=(
            "12-week sales coaching programme",
            "High-ticket closer certification",
            "Sales training for my team",
            "1:1 sales coaching",
            "Career switch into sales",
        ),
        details=(
            (
                "current_role",
                (
                    "Founder",
                    "Sales executive",
                    "Business owner",
                    "Student",
                    "Working professional",
                    "Freelancer",
                ),
            ),
            ("when_to_start", ("This month", "Next month", "Just exploring")),
        ),
        cities=(
            "Pune",
            "Mumbai",
            "Thane",
            "Navi Mumbai",
            "Nashik",
            "Nagpur",
            "Kolhapur",
            "Aurangabad",
            "Bengaluru",
            "Hyderabad",
            "Delhi",
            "Ahmedabad",
        ),
        daily=(3, 10),
        cold=(
            ColdList("File: Past enquiries 2025.xlsx", 100, 2, "Enquired in 2025, never joined"),
            ColdList(
                "File: Business owners directory, Pune.xlsx", 900, -2, "Business owners, Pune"
            ),
        ),
        deals=(45000, 60000, 60000, 75000, 95000),
        meeting=(
            "google_meet",
            "Programme walkthrough and fit check (fictional)",
            "https://meet.example.com/ac-sandbox",
            None,
        ),
        phones=10000,
    ),
    "cyber": OrgSpec(
        key="cyber",
        name="Fortline Cyber Institute (Sandbox)",
        sellers=(
            Seller("Karan", "Mehta", "Mumbai", "cy.karan", 0, 5.5, 0.05, 0.03, 2, 1.0, 0, 1.1),
            Seller(
                "Neha", "Gupta", "Pune", "cy.neha", 5, 6.5, 0.06, 0.04, 0, 1.2, 0, 1.05, "inbound"
            ),
            Seller(
                "Imran",
                "Qureshi",
                "Mumbai",
                "cy.imran",
                15,
                8.0,
                0.35,
                0.2,
                10,
                0.9,
                0,
                0.95,
                "cold",
            ),
            Seller("Pooja", "Nair", "Pune", "cy.pooja", 5, 7.0, 0.1, 0.08, 2, 1.1, 0, 1.0),
            Seller("Vikas", "Yadav", "Pune", "cy.vikas", 20, 8.5, 0.2, 0.15, 1, 0.85, 9, 0.85),
        ),
        sources=(
            Source("meta", "Meta Ads: Ethical hacking course form", 22),
            Source("meta", "Meta Ads: Free demo class form", 18),
            Source("webhook", "Google Ads: Cyber security course form", 22),
            Source("webhook", "Website: /courses/ethical-hacking", 12),
            Source("webhook", "Website: /courses/soc-analyst", 8),
            Source("webhook", "YouTube: Ethical hacking demo video enquiry", 18),
        ),
        interests=(
            "Certified ethical hacker (CEH) prep",
            "SOC analyst job programme",
            "Cyber security basics (weekend batch)",
            "Web application pentesting",
            "Network security diploma",
        ),
        details=(
            ("qualification", ("B.Tech", "BCA", "B.Sc IT", "12th pass", "Working in IT", "MCA")),
            ("preferred_batch", ("Weekday evening", "Weekend", "Online live")),
        ),
        cities=(
            "Pune",
            "Mumbai",
            "Thane",
            "Navi Mumbai",
            "Nashik",
            "Nagpur",
            "Kolhapur",
            "Satara",
            "Bengaluru",
            "Hyderabad",
            "Indore",
            "Surat",
        ),
        daily=(3, 10),
        cold=(
            ColdList(
                "File: Past demo-class sign-ups.xlsx", 100, 2, "Demo class 2025, not enrolled"
            ),
            ColdList(
                "File: Engineering colleges final-year list.xlsx", 900, -2, "Final-year students"
            ),
        ),
        deals=(28000, 42000, 42000, 65000, 85000),
        meeting=(
            "in_person",
            "Free demo class and counselling (fictional)",
            None,
            "Fortline campus, Baner, Pune (fictional)",
        ),
        phones=20000,
    ),
}


# ----- the input -------------------------------------------------------------------------


def _refuse(reason: str, **extra: Any) -> SystemExit:
    return SystemExit(json.dumps({"refused": reason, **extra}))


def spec_of(raw: str) -> dict[str, Any]:
    """The input, checked: inline JSON or a file."""
    if raw.lstrip().startswith("{"):
        body = dict(json.loads(raw))
    else:
        with open(raw, encoding="utf-8") as file:
            body = dict(json.load(file))
    needed = (
        "command_id",
        "approver_email",
        "issue",
        "owner_email",
        "admin_email",
        "seller_mailbox",
        "organisations",
    )
    missing = [name for name in needed if not body.get(name)]
    if missing:
        raise _refuse("missing_input", fields=missing)
    UUID(str(body["command_id"]))
    organisations = list(body["organisations"])
    if not organisations or any(key not in ORGS for key in organisations):
        raise _refuse("unknown_organisation", known=sorted(ORGS))
    if len(set(organisations)) != len(organisations):
        raise _refuse("organisation_twice")
    if "@" not in str(body["seller_mailbox"]):
        raise _refuse("seller_mailbox_not_an_email")
    days = int(body.get("days", 30))
    scale = float(body.get("scale", 1.0))
    if not 1 <= days <= 60:
        raise _refuse("days_out_of_range")
    if not 0.02 <= scale <= 2:
        raise _refuse("scale_out_of_range")
    hashes = {str(k).lower(): str(v) for k, v in dict(body.get("password_hashes") or {}).items()}
    if any(not VERIFIER.match(value) for value in hashes.values()):
        raise _refuse("password_hash_not_a_verifier")
    end = date.fromisoformat(str(body["end"])) if body.get("end") else None
    # Words after each name, so a second build sits beside an earlier one (dev).
    suffix = " ".join(str(body.get("name_suffix") or "").split())
    if len(suffix) > 24:
        raise _refuse("name_suffix_too_long")
    return {
        **body,
        "name_suffix": suffix,
        "organisations": organisations,
        "days": days,
        "scale": scale,
        "end": end,
        "password_hashes": hashes,
        "test_data": body.get("test_data", True) is not False,
        "require_pipeline": body.get("require_pipeline", True) is not False,
    }


def seller_email(mailbox: str, seller: Seller) -> str:
    local, domain = mailbox.strip().lower().split("@", 1)
    return f"{local.split('+', 1)[0]}+{seller.alias}@{domain}"


def logins(spec: dict[str, Any]) -> dict[str, list[str]]:
    """The sellers' sign-in emails, per organisation."""
    return {
        key: [seller_email(spec["seller_mailbox"], seller) for seller in ORGS[key].sellers]
        for key in spec["organisations"]
    }


def _mask(email: str | None) -> str:
    if not email or "@" not in email:
        return "[none]"
    local, domain = email.rsplit("@", 1)
    return f"{local[:1]}***@{domain}"


# ----- the plan: pure, deterministic -----------------------------------------------------


def rng_for(command_id: UUID, *parts: object) -> random.Random:
    digest = hashlib.sha256(":".join([str(command_id), *map(str, parts)]).encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))  # noqa: S311 - a plan, not a secret


def pick(rng: random.Random, weighted: Sequence[tuple[Any, float]]) -> Any:
    return rng.choices([item for item, _ in weighted], [w for _, w in weighted])[0]


def at(day: date, clock: time) -> datetime:
    return datetime.combine(day, clock, tzinfo=IST).astimezone(UTC)


def fictional_phone(spec: OrgSpec, number: int) -> str:
    """+91 00000 xxxxx: Indian in shape, but no Indian number starts with 0 after +91."""
    return f"+91 00000 {spec.phones + number:05d}"


class Shape(NamedTuple):
    """A seller's working day: when they work, as windows between lunch and gaps."""

    start: datetime
    end: datetime
    lunch: tuple[datetime, datetime]
    gaps: tuple[tuple[datetime, datetime], ...]

    @property
    def windows(self) -> tuple[tuple[datetime, datetime], ...]:
        cuts = sorted((self.lunch, *self.gaps))
        out: list[tuple[datetime, datetime]] = []
        begin = self.start
        for cut_start, cut_end in cuts:
            if cut_start > begin:
                out.append((begin, min(cut_start, self.end)))
            begin = max(begin, cut_end)
        if begin < self.end:
            out.append((begin, self.end))
        return tuple(window for window in out if window[1] > window[0])


def day_shape(rng: random.Random, seller: Seller, day: date, index: int) -> Shape | None:
    """The seller's day, or None for a day off (Sunday, before they join, or leave)."""
    if day.weekday() not in WORK_DAYS or index < seller.joins or rng.random() < 0.04:
        return None
    base = datetime.combine(day, DAY_START, tzinfo=IST)
    start = base + timedelta(minutes=max(0, seller.late + rng.gauss(0, 7)))
    end = datetime.combine(day, DAY_END, tzinfo=IST) - timedelta(minutes=rng.uniform(1, 25))
    lunch_start = datetime.combine(day, time(13, 15), tzinfo=IST) + timedelta(
        minutes=rng.uniform(0, 40)
    )
    lunch = (lunch_start, lunch_start + timedelta(minutes=rng.uniform(35, 55)))
    gaps: list[tuple[datetime, datetime]] = []
    if rng.random() < seller.gaps:
        for _ in range(1 if rng.random() < 0.7 else 2):
            length = timedelta(minutes=rng.uniform(60, 120))
            for _attempt in range(20):
                begins = datetime.combine(day, time(11, 15), tzinfo=IST) + timedelta(
                    minutes=rng.uniform(0, 380)
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
    return Shape(
        start.astimezone(UTC),
        end.astimezone(UTC),
        (lunch[0].astimezone(UTC), lunch[1].astimezone(UTC)),
        tuple((a.astimezone(UTC), b.astimezone(UTC)) for a, b in sorted(gaps)),
    )


def arrivals(rng: random.Random, spec: OrgSpec, day: date, scale: float) -> list[datetime]:
    """When the day's Inbound enquiries come in: a steady 3 to 10 a day, at any hour (ads run
    every day), most in the evening."""
    count = max(0, round(rng.randint(*spec.daily) * scale))
    times = []
    for _ in range(count):
        hour = rng.choices(range(24), HOURS)[0]
        times.append(
            datetime.combine(day, time(hour, rng.randrange(60), rng.randrange(60)), tzinfo=IST)
        )
    return sorted(moment.astimezone(UTC) for moment in times)


def talk_seconds(rng: random.Random, outcome: str, talk: float) -> int:
    """How long a connected call lasted, by what came of it."""
    low, high = {
        "lost": (35, 160),
        "junk": (20, 90),
        "int": (150, 660),
        "open": (120, 480),
        "again": (90, 420),
        "meet": (300, 900),
        "meet_far": (300, 900),
        "won": (480, 1500),
        "later": (25, 80),
    }[outcome]
    return max(8, round(rng.uniform(low, high) * talk))


def next_slot(rng: random.Random, after: datetime, *, days: tuple[int, int]) -> datetime:
    """A follow-up or meeting time a seller would pick: a working day some days on, on
    the half hour between 11:00 and 18:00."""
    day = after.astimezone(IST).date() + timedelta(days=rng.randint(*days))
    while day.weekday() not in WORK_DAYS:
        day += timedelta(days=1)
    clock = time(rng.randint(11, 17), rng.choice((0, 30)))
    return at(day, clock)


# ----- the simulation: the app's own code, minute by minute ------------------------------


class _Desk(LeadDesk):
    """The app's desk; the generator never reads a write's answer, so it skips building
    the lead's whole page after each one."""

    async def detail(self, lead_id: UUID) -> Any:  # noqa: ARG002
        return None


class Actor(NamedTuple):
    person_id: UUID
    role: str
    name: str


class Held:
    """A lead the simulation works: the app's row, and what the seller remembers."""

    __slots__ = (
        "lead",
        "owner",
        "cold",
        "phase",
        "misses",
        "talks",
        "task",
        "skip_day",
        "parked",
        "meeting_end",
        "script",
    )

    def __init__(
        self, lead: Lead, owner: int, cold: bool, script: tuple[str, ...] | None = None
    ) -> None:
        self.lead = lead
        self.owner = owner
        self.cold = cold
        self.phase = "new"
        self.misses = 0
        self.talks = 0
        self.task: UUID | None = None
        self.skip_day: date | None = None
        self.parked = False
        self.meeting_end: datetime | None = None
        # A scripted lead's remaining steps (STORIES); None: chance decides.
        self.script = list(script) if script else None

    def next_step(self) -> str | None:
        """A scripted lead's next step: the last one repeats."""
        if not self.script:
            return None
        return self.script.pop(0) if len(self.script) > 1 else self.script[0]


class Run:
    """One organisation's 30 days."""

    def __init__(
        self,
        db: AsyncSession,
        spec: OrgSpec,
        tenant_id: UUID,
        base: UUID,
        people: dict[str, Actor],
        sellers: list[Actor],
        keys: dict[str, str],
        *,
        first: date,
        days: int,
        until: datetime,
        scale: float,
        test_data: bool,
        cold_column: bool,
    ) -> None:
        self.db = db
        self.spec = spec
        self.tenant_id = tenant_id
        self.base = base
        self.people = people
        self.sellers = sellers
        self.keys = keys
        self.first = first
        self.days = days
        self.until = until
        self.scale = scale
        self.test_data = test_data
        self.cold_column = cold_column
        self.rng = rng_for(base, spec.key, "work")
        self.names = rng_for(base, spec.key, "names")
        self.counter = Counter[str]()
        self.held: list[Held] = []
        self.by_seller: list[list[Held]] = [[] for _ in sellers]
        self.by_id: dict[UUID, Held] = {}
        self.shapes: dict[tuple[int, date], Shape | None] = {}
        self.busy: list[list[tuple[datetime, datetime]]] = [[] for _ in sellers]
        self.cold_today: Counter[tuple[int, date]] = Counter()
        self.whatsapp: list[list[UUID]] = [[] for _ in sellers]
        self.used_names: set[str] = set()
        self.phone_count = 0
        self.queue: list[tuple[datetime, int, str, Any]] = []
        self.order = 0
        # The stories still to hand out on each side (Inbound: the first enquiries; Cold: the
        # first rows of the first list).
        self.stories: dict[bool, list[str]] = {False: list(STORIES), True: list(STORIES)}

    def story(self, *, cold: bool) -> tuple[str, ...] | None:
        left = self.stories[cold]
        return STORIES[left.pop(0)] if left else None

    def cold_day(self, item: ColdList) -> int:
        return item.day if item.day >= 0 else self.days + item.day

    # -- helpers ------------------------------------------------------------------------

    def key(self, *parts: object) -> UUID:
        self.counter["commands"] += 1
        return uuid5(self.base, ":".join([self.spec.key, *map(str, parts)]))

    def desk(self, who: Actor, now: datetime) -> _Desk:
        return _Desk(
            self.db,
            Viewer(person_id=who.person_id, tenant_id=self.tenant_id, role=who.role, name=who.name),
            call_mode="simulated",
            sandbox=True,
            now=now,
        )

    def push(self, moment: datetime, kind: str, payload: Any = None) -> None:
        self.order += 1
        heapq.heappush(self.queue, (moment, self.order, kind, payload))

    def name(self) -> str:
        for _ in range(200):
            made = f"{self.names.choice(FIRST_NAMES)} {self.names.choice(LAST_NAMES)}"
            if made not in self.used_names:
                self.used_names.add(made)
                return made
        made = f"{self.names.choice(FIRST_NAMES)} {self.names.choice(LAST_NAMES)}"
        made = f"{made} {len(self.used_names)}"
        self.used_names.add(made)
        return made

    def phone(self) -> str:
        self.phone_count += 1
        return fictional_phone(self.spec, self.phone_count)

    def record(self, *, cold: ColdList | None) -> dict[str, Any]:
        name = self.name()
        rng = self.names
        record: dict[str, Any] = {
            "name": name,
            "phone": self.phone(),
            "city": rng.choice(self.spec.cities),
            "language": rng.choice(("Marathi", "Hindi", "English", "Hindi", "English")),
        }
        if cold:
            record["list"] = cold.reason
            if rng.random() < 0.5:
                record["interest"] = rng.choice(self.spec.interests)
        else:
            record["interest"] = rng.choice(self.spec.interests)
            for field, options in self.spec.details:
                record[field] = rng.choice(options)
        if rng.random() < 0.4:
            local = re.sub(r"[^a-z.]", "", name.lower().replace(" ", "."))
            record["email"] = f"{local}{rng.randrange(10, 99)}@example.com"
        return record

    def shape(self, index: int, day: date) -> Shape | None:
        found = (index, day)
        if found not in self.shapes:
            self.shapes[found] = day_shape(
                rng_for(self.base, self.spec.key, "day", index, day),
                self.spec.sellers[index],
                day,
                (day - self.first).days,
            )
        return self.shapes[found]

    def keep(
        self, lead: Lead, owner: int, *, cold: bool, script: tuple[str, ...] | None = None
    ) -> Held:
        held = Held(lead, owner, cold, script)
        self.held.append(held)
        self.by_seller[owner].append(held)
        self.by_id[lead.id] = held
        return held

    def owner_index(self, lead: Lead) -> int | None:
        for index, seller in enumerate(self.sellers):
            if seller.person_id == lead.owner_person_id:
                return index
        return None

    # -- the setup ----------------------------------------------------------------------

    async def setup(self, start: datetime) -> None:
        owner = self.people["owner"]
        desk = self.desk(owner, start)
        revision, _ = await desk.settings()
        hours: dict[str, Any] = {
            "expected_revision": revision,
            "days": WORK_DAYS,
            "start": DAY_START.strftime("%H:%M"),
            "end": DAY_END.strftime("%H:%M"),
            "pause_leads": False,
        }
        if "breaks" in WorkHoursCommand.model_fields:
            # Lunch is the team's set break; any other gap between calls shows red.
            hours["breaks"] = (
                {"start": LUNCH[0].strftime("%H:%M"), "end": LUNCH[1].strftime("%H:%M")},
            )
        await desk.save_work_hours(WorkHoursCommand(**hours))
        # The owner and the coach take no leads; the sellers take all, without a limit.
        for who in (self.people["owner"], self.people["admin"]):
            await desk.save_rep(
                who.person_id, RepRules(expected_revision=0, available=False, max_open=None)
            )
        for index, who in enumerate(self.sellers):
            seller = self.spec.sellers[index]
            await desk.save_rep(
                who.person_id,
                RepRules(
                    expected_revision=0,
                    # A Cold-only seller takes no new enquiries.
                    available=seller.joins == 0 and seller.sides != "cold",
                    max_open=None,
                ),
            )

    # -- events -------------------------------------------------------------------------

    async def simulate(self) -> None:
        start = at(self.first, time(9, 0))
        await self.setup(start)
        for offset in range(self.days):
            self.push(at(self.first + timedelta(days=offset), time(0, 0)), "day", offset)
        while self.queue:
            moment, _, kind, payload = heapq.heappop(self.queue)
            if moment > self.until:
                break
            if kind == "day":
                self.begin_day(payload)
            elif kind == "arrive":
                await self.arrive(moment, *payload)
            elif kind == "cold":
                await self.upload(moment, payload)
            elif kind == "join":
                await self.join(moment, payload)
            elif kind == "seller":
                await self.turn(moment, payload)
            elif kind == "meeting":
                await self.meeting(moment, payload)
        await self.cover()
        await self.db.flush()

    async def cover(self) -> None:
        """Each side ends with a meeting still to come: where none is booked, the seller of an
        Interested or Open lead books one at the end of the day, as the Meeting button does."""
        for cold in (False, True):
            if any(h.cold == cold and h.phase == "meet" for h in self.held):
                continue
            chosen = next(
                (h for h in self.held if h.cold == cold and h.phase in ("int", "open")), None
            )
            if chosen is None:
                continue
            # The last working evening up to the end (yesterday's, before today's ends).
            day = self.until.astimezone(IST).date()
            moment = at(day, time(18, 30))
            if moment > self.until - timedelta(minutes=10):
                moment = at(day - timedelta(days=1), time(18, 30))
            moment = max(moment, chosen.lead.updated_at)
            mode, agenda, link, place = self.spec.meeting
            starts = next_slot(self.rng, moment, days=(2, 4))
            lead = chosen.lead
            await self.desk(
                self.sellers[chosen.owner], moment
            ).schedule_meeting(
                lead.id,
                MeetingCommand(
                    command_id=self.key("cover-meeting", lead.id),
                    expected_revision=lead.revision,
                    meeting=MeetingInput(
                        starts_at=starts,
                        duration_minutes=45,
                        mode=mode,  # type: ignore[arg-type]
                        link=f"{link}/{lead.id.hex[:10]}" if link else None,
                        location=place,
                        agenda=agenda,
                    ),
                ),
            )
            chosen.phase = "meet"
            self.counter["meetings_booked"] += 1

    def begin_day(self, offset: int) -> None:
        day = self.first + timedelta(days=offset)
        rng = rng_for(self.base, self.spec.key, "arrivals", day)
        typed = [source for source in self.spec.sources if source.typed]
        online = [source for source in self.spec.sources if not source.typed]
        for moment in arrivals(rng, self.spec, day, self.scale):
            source = pick(rng, [(s, s.weight) for s in self.spec.sources])
            if source.typed:
                # Typed in by a seller at work: during the day, by whoever is in.
                moment = at(day, time(rng.randint(11, 18), rng.randrange(60)))
                working = [i for i in range(len(self.sellers)) if self.shape(i, day)]
                if not working:
                    source = pick(rng, [(s, s.weight) for s in online])
                    self.push(moment, "arrive", (source, None, rng.random() < 0.03))
                    continue
                self.push(moment, "arrive", (typed[0], rng.choice(working), False))
            else:
                self.push(moment, "arrive", (source, None, rng.random() < 0.03))
        for which, item in enumerate(self.spec.cold):
            if offset == self.cold_day(item):
                self.push(at(day, time(11, 20)), "cold", which)
        for index, seller in enumerate(self.spec.sellers):
            if seller.joins and offset == seller.joins:
                self.push(at(day, time(10, 5)), "join", index)
            shape = self.shape(index, day)
            if shape is not None:
                self.push(shape.start, "seller", index)

    async def arrive(
        self, moment: datetime, source: Source, typist: int | None, again: bool
    ) -> None:
        if again and self.held:
            # The same person enquires again: the app counts a repeat on their lead.
            earlier = self.rng.choice([h for h in self.held if not h.cold] or self.held)
            record = {
                "name": earlier.lead.name,
                "phone": earlier.lead.phone,
                "interest": earlier.lead.interest,
            }
        else:
            record = self.record(cold=None)
        actor = self.sellers[typist] if typist is not None else self.people["owner"]
        desk = self.desk(actor, moment)
        self.counter["arrivals"] += 1
        number = self.counter["arrivals"]
        lead, outcome = await desk.ingest(
            record,
            source=source.source,
            source_label=source.label,
            source_ref=None if source.typed else f"syn-{self.spec.key}-{number}",
            assign="me" if typist is not None else "rules",
            actor=actor.person_id if typist is not None else None,
            test_data=self.test_data,
            command_id=self.key("arrive", number),
            received_at=moment,
        )
        self.counter[f"live_{outcome}"] += 1
        if outcome != "created" or lead is None:
            return
        owner = self.owner_index(lead)
        if owner is None:
            self.counter["live_unassigned"] += 1
            return
        self.keep(lead, owner, cold=False, script=self.story(cold=False))

    async def upload(self, moment: datetime, which: int) -> None:
        """The coach uploads a list to Cold Leads, given out evenly to the sellers in."""
        item = self.spec.cold[which]
        coach = self.people["admin"]
        desk = self.desk(coach, moment)
        # Everyone in by then works the list, but an Inbound-only seller.
        team = [
            i
            for i, s in enumerate(self.spec.sellers)
            if s.joins <= self.cold_day(item) and s.sides != "inbound"
        ]
        size = max(1, round(item.size * self.scale))
        for row in range(size):
            record = self.record(cold=item)
            owner = team[row % len(team)]
            lead, outcome = await desk.ingest(
                record,
                source="csv",
                source_label=item.label,
                source_ref=f"syn-{self.spec.key}-cold-{which}-{row}",
                assign="person",
                person_id=self.sellers[owner].person_id,
                actor=coach.person_id,
                test_data=self.test_data,
                command_id=self.key("cold", which, row),
            )
            self.counter[f"cold_{outcome}"] += 1
            if outcome == "created" and lead is not None:
                if self.cold_column:
                    lead.pipeline = "cold"
                self.keep(lead, owner, cold=True, script=self.story(cold=True))

    async def join(self, moment: datetime, index: int) -> None:
        """A new seller starts: they take new leads from today."""
        desk = self.desk(self.people["owner"], moment)
        person_id = self.sellers[index].person_id
        row = await self.db.get(LeadRep, (self.tenant_id, person_id))
        await desk.save_rep(
            person_id,
            RepRules(expected_revision=row.revision if row else 0, available=True, max_open=None),
        )

    # -- a seller's turn ------------------------------------------------------------------

    def window_at(self, index: int, moment: datetime) -> datetime | None:
        """The moment itself when the seller is at work, the next moment they are, or None
        when their day is over."""
        shape = self.shape(index, moment.astimezone(IST).date())
        if shape is None:
            return None
        for begin, end in shape.windows:
            if moment < begin:
                return begin
            if begin <= moment < end:
                for busy_start, busy_end in self.busy[index]:
                    if busy_start <= moment < busy_end:
                        return busy_end
                return moment
        return None

    def choose(self, index: int, moment: datetime) -> Held | None:
        """What the seller calls next, as the app's queue puts it: follow-ups due first,
        then new live leads (oldest first), then due retries, then the cold list."""
        day = moment.astimezone(IST).date()
        seller = self.spec.sellers[index]
        due: list[Held] = []
        fresh: list[Held] = []
        retry: list[Held] = []
        cold: list[Held] = []
        for held in self.by_seller[index]:
            lead = held.lead
            if (
                held.parked
                or held.phase in ("meet", "won", "lost", "junk")
                or lead.created_at > moment
            ):
                continue
            if held.phase in ("open", "int", "done"):
                if lead.next_action_at is not None and lead.next_action_at <= moment:
                    if held.skip_day == day:
                        continue
                    if self.rng.random() < seller.skip:
                        held.skip_day = day  # left for another day: it goes overdue
                        continue
                    due.append(held)
            elif held.cold:
                if held.phase == "new" or (
                    lead.next_action_at is not None and lead.next_action_at <= moment
                ):
                    cold.append(held)
            elif held.phase == "new":
                fresh.append(held)
            elif lead.next_action_at is not None and lead.next_action_at <= moment:
                retry.append(held)
        if due:
            return min(due, key=lambda h: h.lead.next_action_at or moment)
        if fresh:
            return min(fresh, key=lambda h: h.lead.created_at)
        if retry:
            return min(retry, key=lambda h: h.lead.next_action_at or moment)
        if cold and self.cold_today[(index, day)] < seller.cold_cap:
            self.cold_today[(index, day)] += 1
            # A cold retry that is due first, then the untouched list.
            return min(
                cold, key=lambda h: (h.phase == "new", h.lead.next_action_at or h.lead.created_at)
            )
        return None

    async def turn(self, moment: datetime, index: int) -> None:
        start = self.window_at(index, moment)
        if start is None:
            return
        if start != moment:
            self.push(start, "seller", index)
            return
        seller = self.spec.sellers[index]
        await self.whatsapp_done(index, moment)
        held = self.choose(index, moment)
        if held is None:
            self.push(moment + timedelta(minutes=self.rng.uniform(12, 25)), "seller", index)
            return
        ended = await self.call(index, held, moment)
        think = min(20.0, max(1.0, self.rng.expovariate(1 / seller.think)))
        self.push(ended + timedelta(minutes=think), "seller", index)

    async def whatsapp_done(self, index: int, moment: datetime) -> None:
        """WhatsApp tasks from earlier calls: most are sent at the next free moment."""
        waiting, self.whatsapp[index] = self.whatsapp[index], []
        for task_id in waiting:
            task = await self.db.get(LeadTask, task_id)
            if task is None or task.status != "open" or task.starts_at > moment:
                if task is not None and task.status == "open":
                    self.whatsapp[index].append(task_id)
                continue
            if self.rng.random() < 0.82:
                await self.finish(index, task_id, moment)

    async def finish(self, index: int, task_id: UUID, moment: datetime) -> None:
        task = await self.db.get(LeadTask, task_id)
        if task is None or task.status != "open":
            return
        await task_book.TaskBook(self.desk(self.sellers[index], moment)).done(
            task_id,
            TaskAction(command_id=self.key("task-done", task_id), expected_revision=task.revision),
        )
        self.counter["tasks_done"] += 1

    async def task(
        self, index: int, held: Held, moment: datetime, kind: str, due: datetime
    ) -> UUID:
        command_id = self.key("task", kind, held.lead.id, moment.isoformat())
        made = await task_book.TaskBook(self.desk(self.sellers[index], moment)).create(
            held.lead.id,
            TaskCommand(
                command_id=command_id,
                kind=kind,  # type: ignore[arg-type]
                starts_at=due,
                source="after_call",
                remind_before_minutes=10 if kind == "call_back" else None,
            ),
        )
        self.counter[f"tasks_{kind}"] += 1
        return made.task_id

    async def call(self, index: int, held: Held, moment: datetime) -> datetime:
        """One call: the phone logs it (start and seconds), then the seller answers the
        after-call sheet, and sets the follow-up, task or meeting it led to."""
        rng = self.rng
        seller = self.spec.sellers[index]
        who = self.sellers[index]
        lead = held.lead
        phase = held.phase
        scripted = held.next_step()
        if scripted is not None:
            # A scripted lead answers when the story needs it (a follow-up may ring out, and
            # the lead stays where it is), and the talk goes the story's way.
            connected = scripted != "again" or rng.random() < 0.45
            outcome = scripted if connected else "nc"
            if outcome == "late":
                # Booked in the last five days, six to eight days ahead: still to come.
                outcome = "meet_far" if moment >= self.until - timedelta(days=5) else "again"
            if outcome == "int" and phase in ("open", "int", "done"):
                outcome = "again"
            if phase == "done" and outcome not in ("won", "lost", "again"):
                outcome = "again"  # after Meeting Done: Won, Lost or another follow-up
        else:
            chance = {
                "new": 0.24 if held.cold else 0.38,
                "nc": 0.18 if held.cold else 0.25,
                "open": 0.4,
                "int": 0.42,
                "done": 0.5,
            }[phase]
            connected = rng.random() < min(0.95, chance * seller.connect)
            outcome = "nc"
        if connected and scripted is None:
            if phase in ("new", "nc"):
                table = (
                    (("int", 10), ("open", 12), ("meet", 2), ("lost", 56), ("junk", 14))
                    + (("later", 6),)
                    if held.cold
                    else (("int", 30), ("open", 16), ("meet", 5), ("lost", 33), ("junk", 8))
                    + (("later", 8),)
                )
            elif phase == "open":
                # Open Leads: the talk goes on, turns into interest, or ends.
                # Never Junk from here: it was a real conversation (handoff, section 10B).
                table = (
                    (("int", 33), ("again", 38), ("meet", 7), ("lost", 22))
                    if held.talks < 4
                    else (("int", 30), ("lost", 70))
                )
            elif phase == "int":
                # A confirmed purchase may go straight to Won.
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
            outcome = pick(rng, table)
        if outcome == "open" and "open" not in self.keys:
            outcome = "int"  # a stage list without Open Leads: it is Interested
        if outcome == "won" and phase != "done" and "junk" not in self.keys:
            outcome = "meet"  # the older stage list wins only after a meeting
        seconds = talk_seconds(rng, outcome, seller.talk) if connected else 0
        ring = timedelta(seconds=rng.uniform(18, 40)) if not connected else timedelta(0)
        ended = moment + timedelta(seconds=seconds) + ring
        await self.desk(who, ended + timedelta(seconds=rng.uniform(30, 120))).log_phone_calls(
            PhoneLog(
                device_id=uuid5(self.base, f"{self.spec.key}:phone:{index}"),
                calls=(
                    PhoneLogCall(
                        log_id=f"syn{self.counter['calls'] + 1}",
                        number=lead.phone or "",
                        started_at=moment,
                        duration_seconds=seconds,
                        direction="outgoing",
                    ),
                ),
            )
        )
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
        if old_task is not None and old_task != held.task:
            await self.finish(index, old_task, answered)
        return answered

    async def not_connected(self, index: int, held: Held, desk: _Desk, now: datetime) -> None:
        rng = self.rng
        reasons = (
            NC_REASONS
            if held.misses == 0
            else tuple(item for item in NC_REASONS if item[0] not in NO_RETRY)
        )
        reason = pick(rng, reasons)
        lead = held.lead
        await desk.dispose(
            lead.id,
            Disposition(
                command_id=self.key("dispose", lead.id, now.isoformat()),
                expected_revision=lead.revision,
                connected=False,
                reason=reason,
            ),
        )
        held.misses += 1
        if held.phase in ("open", "int", "done"):
            # Still interested, just not reached: the seller sets the call back again.
            if lead.next_action_at is not None and rng.random() < 0.7:
                held.task = await self.task(index, held, now, "call_back", lead.next_action_at)
            else:
                held.task = None
            return
        held.phase = "nc"
        if reason in NO_RETRY:
            if "junk" in self.keys:
                # The number is confirmed dead: Junk Lead, invalid contact (never for silence).
                await desk.move(
                    lead.id,
                    StageMove(
                        command_id=self.key("junk-number", lead.id),
                        expected_revision=lead.revision,
                        step=self.keys["junk"],
                        outcome_reason="invalid_number",
                        via="sheet",
                    ),
                )
                held.phase = "junk"
                self.counter["junk_invalid_number"] += 1
            else:
                held.parked = True
            return
        # A lead that never answers: most are closed as Lost (no response); the rest stay Not
        # connected, nobody calling them (the cold list moves on after two tries).
        gave_up = (held.cold and held.misses >= 2 and rng.random() < 0.65) or (
            not held.cold and held.misses >= 6 and rng.random() < 0.85
        )
        if (held.cold and held.misses >= 2) or (not held.cold and held.misses >= 6):
            if gave_up:
                await desk.move(
                    lead.id,
                    StageMove(
                        command_id=self.key("give-up", lead.id),
                        expected_revision=lead.revision,
                        step=self.keys["lost"],
                        outcome_reason="no_response",
                        via="sheet",
                    ),
                )
                held.phase = "lost"
                self.counter["lost_no_response"] += 1
            else:
                held.parked = True

    async def connected(
        self, index: int, held: Held, desk: _Desk, now: datetime, outcome: str
    ) -> None:
        rng = self.rng
        lead = held.lead
        held.talks += 1
        command_id = self.key("dispose", lead.id, now.isoformat())
        held.task = None
        if outcome == "junk" and "junk" in self.keys:
            # Never a real lead: the Junk Lead stage, with why.
            reason = pick(rng, JUNK_REASONS)
            await desk.dispose(
                lead.id,
                Disposition(
                    command_id=command_id,
                    expected_revision=lead.revision,
                    connected=True,
                    step=self.keys["junk"],
                    outcome_reason=reason,
                ),
            )
            held.phase = "junk"
            self.counter[f"junk_{reason}"] += 1
            return
        if outcome in ("lost", "junk"):
            # Without a Junk stage, a lead that was never real is Lost, "not a lead".
            reason = (
                "not_a_lead"
                if outcome == "junk"
                else pick(rng, FIRST_LOST if held.phase in ("new", "nc") else LATER_LOST)
            )
            await desk.dispose(
                lead.id,
                Disposition(
                    command_id=command_id,
                    expected_revision=lead.revision,
                    connected=True,
                    step=self.keys["lost"],
                    outcome_reason=reason,
                ),
            )
            held.phase = "lost"
            self.counter[f"lost_{reason}"] += 1
            return
        if outcome == "won":
            await desk.dispose(
                lead.id,
                Disposition(
                    command_id=command_id,
                    expected_revision=lead.revision,
                    connected=True,
                    step=self.keys["won"],
                    deal_value=str(rng.choice(self.spec.deals)),
                    remark="Paid the first instalment (fictional).",
                ),
            )
            held.phase = "won"
            self.counter["won"] += 1
            return
        if outcome in ("meet", "meet_far"):
            mode, agenda, link, place = self.spec.meeting
            starts = next_slot(rng, now, days=(6, 8) if outcome == "meet_far" else (1, 3))
            minutes = rng.choice((30, 45, 60))
            await desk.dispose(
                lead.id,
                Disposition(
                    command_id=command_id,
                    expected_revision=lead.revision,
                    connected=True,
                    step=self.keys["meet"],
                    follow_up_at=starts,
                    meeting=MeetingInput(
                        starts_at=starts,
                        duration_minutes=minutes,
                        mode=mode,  # type: ignore[arg-type]
                        link=f"{link}/{lead.id.hex[:10]}" if link else None,
                        location=place,
                        agenda=agenda,
                    ),
                ),
            )
            held.phase = "meet"
            held.meeting_end = starts + timedelta(minutes=minutes)
            self.busy[index].append((starts, held.meeting_end))
            self.counter["meetings_booked"] += 1
            self.push(held.meeting_end + timedelta(minutes=rng.uniform(5, 40)), "meeting", lead.id)
            return
        # A follow-up with a reminder: inside Open Leads (the talk goes on), Interested, or
        # Meeting Done; "again" keeps the lead where it is.
        if outcome == "later":
            follow = now + timedelta(hours=rng.choice((2, 3, 4)))
            if follow.astimezone(IST).time() >= time(18, 30):
                follow = next_slot(rng, now, days=(1, 1))
        else:
            follow = next_slot(rng, now, days=(1, 3))
        if outcome == "again" and held.phase in ("open", "done"):
            stays = held.phase
        elif outcome == "open" or (
            # "Call later" from a first talk is Open Leads; an Interested lead stays Interested.
            outcome == "later" and held.phase in ("new", "nc") and "open" in self.keys
        ):
            stays = "open"
        else:
            stays = "int"
        if stays == "open":
            # Open Leads always carries its reason: Call later or Discussion incomplete.
            why = "Call later" if outcome == "later" else pick(rng, OPEN_REASONS)
            detail = rng.choice(
                ("Busy at work, call after 6.", "Driving, asked to call tomorrow.")
                if why == "Call later"
                else ("Line dropped mid-talk.", "Wants details before deciding to talk.")
            )
            remark = f"{why}: {detail}"
        else:
            remark = rng.choice(
                (
                    "Wants to discuss with family first.",
                    "Asked for the fee breakup.",
                    "Call back after salary day.",
                    "Comparing two options, keen.",
                    "Wants the brochure on WhatsApp.",
                )
            )
        await desk.dispose(
            lead.id,
            Disposition(
                command_id=command_id,
                expected_revision=lead.revision,
                connected=True,
                step=self.keys[stays],
                follow_up_at=follow,
                remark=remark,
            ),
        )
        held.phase = stays
        if rng.random() < 0.88:
            held.task = await self.task(index, held, now, "call_back", follow)
        if outcome != "later" and rng.random() < 0.35:
            self.whatsapp[index].append(
                await self.task(index, held, now, "whatsapp", now + timedelta(minutes=15))
            )
        self.counter["follow_ups_set"] += 1

    async def meeting(self, moment: datetime, lead_id: UUID) -> None:
        """The meeting's time has passed: it happened, they didn't come, or it moved off."""
        held = self.by_id[lead_id]
        if held.phase != "meet":
            return
        row = await meeting_rows.open_meeting(self.db, self.tenant_id, lead_id)
        if row is None:
            return
        rng = self.rng
        who = self.sellers[held.owner]
        desk = self.desk(who, moment)
        lead = held.lead
        what = (
            "done"
            if held.script is not None
            else pick(rng, (("done", 74), ("missed", 18), ("cancelled", 8)))
        )
        follow = next_slot(rng, moment, days=(1, 2))
        if what == "done":
            await desk.meeting_done(
                row.id,
                MeetingDone(
                    command_id=self.key("held", lead_id, moment.isoformat()),
                    expected_revision=lead.revision,
                    note=rng.choice(
                        (
                            "Walked through the plan; deciding this week.",
                            "Liked it; asked about the instalments.",
                            "Joined with a friend; both keen.",
                        )
                    ),
                    next_action_at=follow,
                ),
            )
            held.phase = "done"
            held.talks = 0
            self.counter["meetings_done"] += 1
        else:
            # Missed: still Interested, call again. Cancelled: back to Open Leads, "call later"
            # (a cancelled meeting needs its true new stage, handoff section 10B).
            back = "open" if what == "cancelled" and "open" in self.keys else "int"
            await desk.meeting_not_held(
                row.id,
                MeetingClosed(
                    command_id=self.key("not-held", lead_id, moment.isoformat()),
                    expected_revision=lead.revision,
                    status=what,  # type: ignore[arg-type]
                    step=self.keys[back],
                    next_action_at=follow,
                    note="Didn't join (fictional)."
                    if what == "missed"
                    else "Call later: asked to move it to next month.",
                ),
            )
            held.phase = back
            self.counter[f"meetings_{what}"] += 1
        if rng.random() < 0.85:
            held.task = await self.task(held.owner, held, moment, "call_back", follow)

    async def settle_bells(self, day_start: datetime) -> None:
        """Bell lines from before today were read on their day; today's stay new."""
        await self.db.execute(
            update(Notification)
            .where(
                Notification.tenant_id == self.tenant_id,
                Notification.created_at < day_start,
                Notification.read_at.is_(None),
            )
            .values(read_at=Notification.created_at + timedelta(minutes=7))
            .execution_options(synchronize_session=False)
        )


# ----- accounts, the organisation, the read-back -----------------------------------------


async def _person(db: AsyncSession, email: str) -> Person | None:
    found: Person | None = await db.scalar(
        select(Person).where(func.lower(Person.email) == email.strip().lower())
    )
    return found


async def _seller_account(
    db: AsyncSession, email: str, name: str, verifier: str | None, base: UUID, now: datetime
) -> tuple[UUID, str]:
    """The seller's account: found, or made verified with its password verifier."""
    found = await _person(db, email)
    if found is not None:
        return found.id, "found"
    if verifier is None:
        raise _refuse("password_hash_missing", email=email)
    person_id = uuid5(base, f"person:{email}")
    await AsyncSqlAlchemyIdentityRepository(db).save_person(
        PersonSnapshot(id=person_id, email=email, display_name=name, email_verified_at=now)
    )
    db.add(PasswordCredential(person_id=person_id, password_hash=verifier))
    await db.flush()
    return person_id, "made"


async def _stages(db: AsyncSession, tenant_id: UUID, by: UUID, now: datetime) -> str:
    """The recommended nine stages when the app has that template, else the stages a new
    organisation gets. Which one, in a word."""
    if not any(item.id == RECOMMENDED for item in TEMPLATES):
        await journeys.start_organisation(db, tenant_id, by, now)
        return journeys.NEW_ORGANISATION_TEMPLATE
    before = await journeys.read(db, tenant_id, journeys.MAIN_PIPELINE)
    stages = journeys.from_template(RECOMMENDED, before, {})
    # In the handoff's order (Open Leads before Not Connected), whatever the template's.
    rank = {milestone: place for place, milestone in enumerate(ORDER)}
    await journeys.save(
        db,
        tenant_id,
        stages=tuple(sorted(stages, key=lambda stage: rank.get(stage.milestone, len(ORDER)))),
        industry=RECOMMENDED,
        expected_version=before.version,
        note="The recommended nine stages, for a sandbox organisation",
        by=by,
        now=now,
        pipeline=journeys.MAIN_PIPELINE,
    )
    return RECOMMENDED


async def _keys(db: AsyncSession, tenant_id: UUID) -> dict[str, str]:
    journey = await journeys.read(db, tenant_id, journeys.MAIN_PIPELINE)
    found: dict[str, str] = {}
    for name, milestone in (*MEANINGS.items(), *OPTIONAL_MEANINGS.items()):
        stage = next((s for s in journey.live if s.milestone == milestone), None)
        if stage is not None:
            found[name] = stage.key
        elif name in MEANINGS:
            raise _refuse("stage_list_lacks_a_meaning", meaning=milestone)
    return found


async def readback(db: AsyncSession, tenant_id: UUID, now: datetime) -> dict[str, Any]:
    """The organisation as the app holds it: people, leads, calls, meetings and tasks."""
    tenant = await db.get(Tenant, tenant_id)
    assert tenant is not None
    members = (
        await db.execute(
            select(Membership.role, Person.display_name, Person.email, Person.id)
            .join(Person, Person.id == Membership.person_id)
            .where(Membership.tenant_id == tenant_id, Membership.ended_at.is_(None))
            .order_by(Membership.role, Person.display_name)
        )
    ).all()
    journey = await journeys.read(db, tenant_id, journeys.MAIN_PIPELINE)
    stages = await journeys.lead_counts(db, tenant_id, journey)
    leads = Counter[str]()
    # Each side's leads by stage, as the seller's tabs show them (Inbound: "live" or empty).
    sides: dict[str, Counter[str]] = {"Inbound": Counter(), "Cold": Counter()}
    # Who holds which side's leads (an Inbound-only and a Cold-only seller show here).
    holders = {person_id: name or _mask(email) for _, name, email, person_id in members}
    held_by: dict[str, Counter[str]] = {}
    tagged = hasattr(Lead, "pipeline")
    columns = [Lead.source, Lead.test_data, Lead.owner_person_id, Lead.stage, Lead.step]
    for row in (
        await db.execute(
            select(*columns, Lead.attempts, *([Lead.pipeline] if tagged else [])).where(
                Lead.tenant_id == tenant_id
            )
        )
    ).all():
        leads["total"] += 1
        leads[f"source:{row[0]}"] += 1
        leads["test_data"] += bool(row[1])
        leads["unassigned"] += row[2] is None
        cold = (row[6] == "cold") if tagged else row[0] == "csv"
        if tagged:
            leads[f"pipeline:{row[6] or 'live'}"] += 1
        found = journey.resolve(row[3], row[4])
        sides["Cold" if cold else "Inbound"][found.label if found else row[3]] += 1
        leads["cold_unworked"] += cold and row[3] == "new" and row[5] == 0
        if row[2] is not None:
            held_by.setdefault(holders.get(row[2], "other"), Counter())[
                "Cold" if cold else "Inbound"
            ] += 1
    calls = Counter[str]()
    by_seller: dict[str, Counter[str]] = {}
    names = {person_id: name or _mask(email) for _, name, email, person_id in members}
    today = datetime.combine(now.astimezone(IST).date(), time.min, tzinfo=IST)
    for actor, data, created in (
        await db.execute(
            select(LeadEvent.actor_person_id, LeadEvent.data, LeadEvent.created_at).where(
                LeadEvent.tenant_id == tenant_id, LeadEvent.kind == "call"
            )
        )
    ).all():
        seconds = int((data or {}).get("duration_seconds") or 0)
        mine = by_seller.setdefault(names.get(actor, "other"), Counter())
        for tally in (calls, mine):
            tally["calls"] += 1
            tally["connected" if seconds > 0 else "not_connected"] += 1
            tally["talk_seconds"] += seconds
            if created >= today:
                tally["today"] += 1
    for tally in (calls, *by_seller.values()):
        tally["talk_minutes"] = round(tally.pop("talk_seconds", 0) / 60)
    meetings = Counter(
        (
            await db.scalars(select(LeadMeeting.status).where(LeadMeeting.tenant_id == tenant_id))
        ).all()
    )
    tasks = Counter[str]()
    for status, due in (
        await db.execute(
            select(LeadTask.status, LeadTask.starts_at).where(LeadTask.tenant_id == tenant_id)
        )
    ).all():
        tasks[status] += 1
        if status == "open":
            tasks["open_overdue" if due < now - timedelta(hours=1) else "open_due_later"] += 1
    lost = Counter(
        (
            await db.scalars(
                select(Lead.outcome_reason).where(
                    Lead.tenant_id == tenant_id, Lead.outcome_reason.is_not(None)
                )
            )
        ).all()
    )
    # Home's "Follow-ups late": open leads whose next call is more than an hour overdue.
    late = await db.scalar(
        select(func.count()).where(
            Lead.tenant_id == tenant_id,
            Lead.stage.in_(("new", "not_connected", "follow_up", "interested")),
            Lead.next_action_at < now - timedelta(hours=1),
        )
    )
    sandbox = await db.get(ConversationSandboxOrganisation, tenant_id)
    bells = int(
        await db.scalar(
            select(func.count()).where(
                Notification.tenant_id == tenant_id, Notification.read_at.is_(None)
            )
        )
        or 0
    )
    return {
        "tenant_id": str(tenant_id),
        "name": tenant.name,
        "sandbox": sandbox is not None,
        "members": [
            {"role": role, "name": name, "email": email if role == "member" else _mask(email)}
            for role, name, email, _ in members
        ],
        "stages": {stage.label: stages.get(stage.key, 0) for stage in journey.live},
        "template": journey.industry,
        "by_side": {
            side: {stage.label: tally.get(stage.label, 0) for stage in journey.live}
            for side, tally in sides.items()
        },
        "leads": dict(sorted(leads.items())),
        "leads_by_seller": {name: dict(tally) for name, tally in sorted(held_by.items())},
        "follow_ups_late": int(late or 0),
        "calls": dict(calls),
        "calls_by_seller": {name: dict(tally) for name, tally in sorted(by_seller.items())},
        "meetings": dict(meetings),
        "tasks": dict(tasks),
        "lost_reasons": dict(lost.most_common()),
        "unread_bells": bells,
    }


async def run_one(
    db: AsyncSession,
    spec: dict[str, Any],
    key: str,
    *,
    mode: Mode,
    now: datetime,
    boundaries: tuple[UUID, UUID],
) -> dict[str, Any]:
    """One organisation: the change, its rehearsal, or its read-back, in the caller's
    transaction."""
    org = ORGS[key]
    if spec.get("name_suffix"):
        org = org._replace(name=f"{org.name} {spec['name_suffix']}")
    base = UUID(str(spec["command_id"]))
    command_id = uuid5(base, f"organisation:{key}")
    report: dict[str, Any] = {"mode": mode, "organisation": org.name}
    if mode == "read":
        await db.execute(text("SET TRANSACTION READ ONLY"))
    prior = await db.scalar(
        select(Organisation).where(Organisation.creation_command_id == command_id)
    )
    if prior is not None:
        report["status"] = "already_applied" if mode != "read" else "read"
        report["after"] = await readback(db, prior.tenant_id, now)
        return report
    report["before"] = {
        "organisation": None,
        "seller_accounts": sum(
            [
                await _person(db, email) is not None
                for email in logins({**spec, "organisations": [key]})[key]
            ]
        ),
    }
    if mode == "read":
        report["status"] = "not_found"
        return report
    cold_column = hasattr(Lead, "pipeline")
    if spec["require_pipeline"] and not cold_column:
        raise _refuse("lead_pipeline_column_missing", needs="migration 20261030_0146")
    approver = await _person(db, spec["approver_email"])
    owner = await _person(db, spec["owner_email"])
    admin = await _person(db, spec["admin_email"])
    if approver is None or owner is None or admin is None:
        raise _refuse(
            "person_not_found",
            approver=approver is not None,
            owner=owner is not None,
            admin=admin is not None,
        )
    twin = await db.scalar(
        select(Tenant.id)
        .join(Membership, Membership.tenant_id == Tenant.id)
        .where(
            Membership.person_id == owner.id,
            Membership.ended_at.is_(None),
            func.lower(Tenant.name) == org.name.lower(),
        )
        .limit(1)
    )
    if twin is not None:
        raise _refuse("owner_has_one_by_this_name", organisation=org.name)

    # 1. The sellers' accounts.
    accounts: list[dict[str, str]] = []
    seller_ids: list[UUID] = []
    for seller in org.sellers:
        email = seller_email(spec["seller_mailbox"], seller)
        person_id, state = await _seller_account(
            db,
            email,
            f"{seller.first} {seller.last}",
            spec["password_hashes"].get(email),
            base,
            now,
        )
        seller_ids.append(person_id)
        accounts.append({"email": email, "name": f"{seller.first} {seller.last}", "is": state})
    report["sellers"] = accounts

    # 2. The organisation, its people, stages and sandbox flag.
    reference = f"approved-data-change:{spec['issue']}"
    why = f"Fictional sandbox organisation ({spec['issue']})"
    service = OrganisationService(
        db, operations_tenant_id=boundaries[0], public_learner_tenant_id=boundaries[1]
    )
    created = await service.create(org.name, owner.id, command_id, reference, reason=why)
    tenant_id = created.tenant_id
    report["stage_list"] = await _stages(db, tenant_id, approver.id, now)
    await service.add_member(
        tenant_id,
        admin.id,
        "admin",
        uuid5(command_id, "member:admin"),
        operator_reference=reference,
        reason=why,
    )
    for person_id in seller_ids:
        await service.add_member(
            tenant_id,
            person_id,
            "member",
            uuid5(command_id, f"member:{person_id}"),
            operator_reference=reference,
            reason=why,
        )
    db.add(
        ConversationSandboxOrganisation(
            tenant_id=tenant_id,
            approved_by_person_id=approver.id,
            approval_reference=f"{spec['issue']}: {org.name}"[:160],
            created_at=now,
        )
    )
    await db.flush()

    # 3. The 30 days.
    last = spec["end"] or now.astimezone(IST).date()
    first = last - timedelta(days=spec["days"] - 1)
    until = min(now, at(last + timedelta(days=1), time(0, 0)))
    people = {
        "owner": Actor(owner.id, "owner", owner.display_name or "Owner"),
        "admin": Actor(admin.id, "admin", admin.display_name or "Admin"),
    }
    sellers = [
        Actor(person_id, "member", f"{s.first} {s.last}")
        for person_id, s in zip(seller_ids, org.sellers, strict=True)
    ]
    work = Run(
        db,
        org,
        tenant_id,
        command_id,
        people,
        sellers,
        await _keys(db, tenant_id),
        first=first,
        days=spec["days"],
        until=until,
        scale=spec["scale"],
        test_data=spec["test_data"],
        cold_column=cold_column,
    )
    await work.simulate()
    await work.settle_bells(datetime.combine(until.astimezone(IST).date(), time.min, tzinfo=IST))
    await db.flush()

    # 4. The audit event.
    await append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_person_id=approver.id,
        actor_type="operator",
        action=ACTION,
        resource_type="tenant",
        resource_id=tenant_id,
        request_id=str(uuid5(command_id, "audit")),
        reason=f"Owner approval ({spec['issue']}): fictional sandbox organisation {org.name}",
        payload={
            "issue": spec["issue"],
            "command_id": str(command_id),
            "first_day": first.isoformat(),
            "last_day": last.isoformat(),
            "scale": spec["scale"],
            "test_data": spec["test_data"],
            "simulated": {k: v for k, v in sorted(work.counter.items()) if k != "commands"},
        },
    )
    report["window"] = {
        "first_day": first.isoformat(),
        "last_day": last.isoformat(),
        "until": until.isoformat(),
    }
    report["simulated"] = {k: v for k, v in sorted(work.counter.items()) if k != "commands"}
    report["after"] = await readback(db, tenant_id, now)
    report["status"] = "applied" if mode == "apply" else "rehearsed_and_rolled_back"
    return report


async def execute(
    sessions: async_sessionmaker[AsyncSession],
    spec: dict[str, Any],
    *,
    mode: Mode,
    now: datetime,
    boundaries: tuple[UUID, UUID],
) -> list[dict[str, Any]]:
    """Each organisation in its own transaction: committed on apply, rolled back otherwise."""
    reports = []
    for key in spec["organisations"]:
        async with sessions() as db:
            try:
                report = await run_one(db, spec, key, mode=mode, now=now, boundaries=boundaries)
            except BaseException:
                await db.rollback()
                raise
            if mode == "apply":
                await db.commit()
            else:
                await db.rollback()
        reports.append(report)
    return reports


async def main(path: str, mode: Mode) -> int:
    spec = spec_of(path)
    settings = get_settings()
    if settings.operations_tenant_id is None or settings.public_learner_tenant_id is None:
        raise _refuse("tenant_boundaries_not_configured")
    engine = create_async_engine(settings.database_url, hide_parameters=True)
    try:
        reports = await execute(
            async_sessionmaker(engine, expire_on_commit=False),
            spec,
            mode=mode,
            now=datetime.now(UTC),
            boundaries=(settings.operations_tenant_id, settings.public_learner_tenant_id),
        )
    finally:
        await engine.dispose()
    print(json.dumps({"approval": spec["issue"], "organisations": reports}, default=str))
    return 0


if __name__ == "__main__":
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--logins" in flags:
        print(json.dumps(logins(spec_of(args[0]))))
        raise SystemExit(0)
    chosen: Mode = "apply" if "--apply" in flags else "read" if "--read" in flags else "dry-run"
    raise SystemExit(asyncio.run(main(args[0], chosen)))
