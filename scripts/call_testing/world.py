# ruff: noqa: E501 - the world is data: one person, product or step per line
"""The test world (docs/qa/test-world/WORLD.md) as data, and a planner that plays one day of it.

Three fictional companies sell every working day: leads arrive, sellers dial inside work hours,
about 40% connect, stories move from one call to the next (a visit agreed on Tuesday happens on
Sunday), and about 15% of connected calls aren't sales. ``plan_day`` turns the world and its
saved state into the day's calls; the same date and state always give the same plan.

Standard library only. Nothing here touches a server: the daily runner executes the plan.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

IST = timezone(timedelta(hours=5, minutes=30), "IST")
WORLD_VERSION = "1"


@dataclass(frozen=True)
class Person:
    key: str
    name: str
    role: str
    languages: tuple[str, ...]
    strength: str
    weakness: str
    cold_only: bool = False


@dataclass(frozen=True)
class Product:
    key: str
    name: str
    price: str


@dataclass(frozen=True)
class Persona:
    key: str
    who: str
    sales: bool
    purpose: (
        str  # call_map.call_purpose kind: sales, support, onboarding, internal, personal, unclear
    )
    weight: int


@dataclass(frozen=True)
class Agency:
    key: str
    name: str
    city: str
    trade: str
    days: tuple[int, ...]
    start: time
    end: time
    lunch: tuple[time, time]
    owner: Person
    sellers: tuple[Person, ...]
    products: tuple[Product, ...]
    sources: tuple[tuple[str, int], ...]
    leads_per_day: tuple[int, int]
    dials_per_seller: tuple[int, int]
    connect_rate: float
    personas: tuple[Persona, ...]
    languages: tuple[tuple[str, int], ...]


def _p(
    key: str, name: str, role: str, langs: str, strength: str, weakness: str, cold: bool = False
) -> Person:
    return Person(key, name, role, tuple(langs.split(",")), strength, weakness, cold)


NOT_SALES = (
    Persona("family", "a family member calls the seller's work phone", False, "personal", 4),
    Persona("manager", "the manager checks the day's numbers", False, "internal", 3),
    Persona("wrong", "a wrong number", False, "unclear", 2),
    Persona("ivr", "a bank or office IVR menu", False, "unclear", 1),
    Persona("silence", "the line connects and nobody speaks", False, "unclear", 1),
)

AGENCIES: tuple[Agency, ...] = (
    Agency(
        key="sahyadri",
        name="TEST · Sahyadri Homes",
        city="Pune",
        trade="real-estate channel partner: new flats for two builders and resale for flat owners",
        days=(0, 1, 2, 3, 4, 5),
        start=time(10, 30),
        end=time(19, 0),
        lunch=(time(13, 30), time(14, 15)),
        owner=_p(
            "rajesh",
            "Rajesh Bhonsle",
            "owner and manager",
            "marathi,hindi,english",
            "knows every builder",
            "calls the team mid-visit to chase numbers",
        ),
        sellers=(
            _p(
                "priya",
                "Priya Nair",
                "senior seller",
                "english,hindi",
                "closes; strong on payment plans",
                "talks too much and goes to price before needs",
            ),
            _p(
                "amol",
                "Amol Jadhav",
                "seller",
                "marathi,hindi",
                "rapport; families trust him",
                "never asks the budget or who else decides",
            ),
            _p(
                "faiz",
                "Faiz Shaikh",
                "new seller",
                "english,hinglish",
                "energy; follows up fast",
                "folds on the first objection and forgets the next step",
            ),
            _p(
                "sneha",
                "Sneha Patil",
                "inside sales, cold lists",
                "marathi-english",
                "gets through sixty dials a day",
                "gives up after the first not interested",
                cold=True,
            ),
        ),
        products=(
            Product("sunleaf-2bhk", "Sunleaf Residences 2BHK, Hinjawadi", "68 to 76 lakh"),
            Product("sunleaf-3bhk", "Sunleaf Residences 3BHK, Hinjawadi", "92 to 98 lakh"),
            Product(
                "riverbend-3bhk",
                "Riverbend Towers 3BHK, Kharadi, ready to move",
                "1.05 to 1.25 crore",
            ),
            Product(
                "resale-mandate", "a resale listing for a flat owner", "1% commission on the deal"
            ),
        ),
        sources=(("meta", 5), ("portal", 3), ("website", 2), ("walk_in", 1), ("referral", 1)),
        leads_per_day=(6, 12),
        dials_per_seller=(40, 60),
        connect_rate=0.4,
        personas=(
            Persona("first_buyer", "a first-time buyer couple", True, "sales", 5),
            Persona("upgrader", "a family upgrading from a 1BHK", True, "sales", 3),
            Persona("investor", "an investor who wants rental yield", True, "sales", 2),
            Persona("nri", "an NRI buying for parents", True, "sales", 1),
            Persona("owner_seller", "a flat owner who wants to sell", True, "sales", 2),
            Persona("co_broker", "another broker who wants to co-broke", True, "sales", 1),
            Persona("tenant", "someone who only wants to rent (not a fit)", True, "sales", 1),
        ),
        languages=(("english", 3), ("marathi-english", 3), ("hinglish", 3)),
    ),
    Agency(
        key="suryoday",
        name="TEST · Suryoday Solar",
        city="Nashik",
        trade="rooftop solar for homes, shops and schools",
        days=(0, 1, 2, 3, 4, 5),
        start=time(10, 30),
        end=time(19, 0),
        lunch=(time(13, 30), time(14, 15)),
        owner=_p(
            "vikas",
            "Vikas Thorat",
            "owner, runs installations",
            "marathi,hindi",
            "technical trust",
            "discounts to close",
        ),
        sellers=(
            _p(
                "ganesh",
                "Ganesh More",
                "senior seller",
                "marathi",
                "explains savings in rupees a month",
                "skips the site-survey booking",
            ),
            _p(
                "kavya",
                "Kavya Iyer",
                "seller, commercial roofs",
                "english,hindi",
                "numbers and payback",
                "long monologues and few questions",
            ),
            _p(
                "rahulp",
                "Rahul Pawar",
                "new seller",
                "hinglish",
                "persistent",
                "can't answer subsidy questions and promises dates",
            ),
        ),
        products=(
            Product(
                "solar-3kw", "3 kW home rooftop system", "1.9 lakh before the government subsidy"
            ),
            Product("solar-5kw", "5 kW home rooftop system", "2.9 lakh before the subsidy"),
            Product("solar-25kw", "25 kW shop or school roof", "11 lakh"),
            Product("amc", "yearly maintenance", "4,500 a year"),
        ),
        sources=(("meta", 3), ("website", 3), ("referral", 2), ("google", 2)),
        leads_per_day=(3, 6),
        dials_per_seller=(25, 35),
        connect_rate=0.45,
        personas=(
            Persona("homeowner", "a homeowner with a big summer bill", True, "sales", 5),
            Persona("society", "a housing-society secretary", True, "sales", 2),
            Persona("shop", "a shop owner", True, "sales", 2),
            Persona("school", "a school's administrator", True, "sales", 1),
            Persona(
                "customer_service",
                "an existing customer: a dirty panel or a meter delay",
                False,
                "support",
                2,
            ),
        ),
        languages=(("marathi-english", 4), ("hinglish", 3), ("english", 2)),
    ),
    Agency(
        key="kavach",
        name="TEST · Kavach Insurance Advisors",
        city="Thane",
        trade="term, health and motor insurance",
        days=(0, 1, 2, 3, 4, 5),
        start=time(10, 0),
        end=time(18, 30),
        lunch=(time(13, 30), time(14, 15)),
        owner=_p(
            "farhan",
            "Farhan Merchant",
            "owner and manager",
            "english,hindi",
            "renewals book",
            "reviews only the wins",
        ),
        sellers=(
            _p(
                "anjali",
                "Anjali Rao",
                "top seller",
                "english",
                "needs analysis; families",
                "skips the medical-disclosure questions",
            ),
            _p(
                "sachin",
                "Sachin Gaikwad",
                "renewals desk",
                "hindi,marathi",
                "never misses a renewal date",
                "reads the script word for word",
            ),
            _p(
                "deepa",
                "Deepa Menon",
                "new seller",
                "english",
                "warm",
                "lets the call end without a follow-up time",
            ),
        ),
        products=(
            Product("term-1cr", "term cover of 1 crore", "12,000 to 18,000 a year"),
            Product(
                "health-floater", "family health floater of 10 lakh", "22,000 to 28,000 a year"
            ),
            Product("motor", "motor renewal", "depends on the car"),
        ),
        sources=(("meta", 3), ("website", 2), ("referral", 2), ("renewal_list", 3)),
        leads_per_day=(4, 8),
        dials_per_seller=(30, 45),
        connect_rate=0.4,
        personas=(
            Persona("young_family", "a young family buying their first cover", True, "sales", 4),
            Persona("renewal", "a customer whose policy renews this month", True, "sales", 3),
            Persona("price_shopper", "someone comparing quotes online", True, "sales", 2),
            Persona(
                "claim_help",
                "an existing customer who needs help with a claim",
                False,
                "support",
                2,
            ),
            Persona("kyc", "a new customer chasing their KYC documents", False, "onboarding", 1),
        ),
        languages=(("english", 4), ("hinglish", 3), ("marathi-english", 1)),
    ),
)

# Story arcs: the call kinds a lead goes through, and the days between them.
ARCS: Mapping[str, tuple[tuple[str, int], ...]] = {
    "win": (("first_call", 0), ("meeting_booking", 2), ("negotiation", 3), ("closing", 2)),
    "slow_win": (
        ("first_call", 0),
        ("follow_up", 2),
        ("follow_up", 7),
        ("negotiation", 2),
        ("closing", 3),
    ),
    "lost": (("first_call", 0), ("meeting_booking", 2), ("objection_lost", 3)),
    "quiet": (("first_call", 0), ("follow_up", 2), ("no_answer", 2), ("no_answer", 3)),
    "junk": (("junk_call", 0),),
    "cold_no": (("cold_opener", 0),),
    "cold_yes": (("cold_opener", 0), ("first_call", 3), ("meeting_booking", 2)),
}
ARC_WEIGHTS = {"win": 2, "slow_win": 2, "lost": 3, "quiet": 3, "junk": 1}
COLD_WEIGHTS = {"cold_no": 8, "cold_yes": 1}
# Seconds for a connected call of each kind (low, high).
LENGTHS: Mapping[str, tuple[int, int]] = {
    "first_call": (120, 300),
    "follow_up": (60, 180),
    "meeting_booking": (180, 360),
    "negotiation": (360, 900),
    "closing": (300, 600),
    "objection_lost": (120, 300),
    "junk_call": (20, 50),
    "cold_opener": (20, 60),
    "no_answer": (0, 0),
    "not_sales": (40, 240),
}


def agency(key: str) -> Agency:
    for item in AGENCIES:
        if item.key == key:
            return item
    raise KeyError(key)


def _rng(*parts: object) -> random.Random:
    seed = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return random.Random(int.from_bytes(seed[:8], "big"))  # noqa: S311 - simulation, not security


def _pick(rng: random.Random, weighted: Sequence[tuple[Any, int]]) -> Any:
    total = sum(w for _, w in weighted)
    roll = rng.uniform(0, total)
    for item, weight in weighted:
        roll -= weight
        if roll <= 0:
            return item
    return weighted[-1][0]


FIRST_NAMES = (
    "Neha",
    "Rohit",
    "Sunita",
    "Vikram",
    "Pooja",
    "Arjun",
    "Kiran",
    "Meena",
    "Sanjay",
    "Asha",
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
)
LAST_NAMES = (
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


@dataclass
class Lead:
    key: str
    agency: str
    name: str
    phone: str
    source: str
    persona: str
    product: str
    language: str
    seller: str
    arc: str
    created: str  # ISO date
    step: int = 0
    next_due: str | None = None
    history: list[dict[str, Any]] = field(default_factory=list)


def _lead_phone(agency_key: str, number: int) -> str:
    """+91 00000 xxxxx: no Indian number starts with 0 after +91, so it rings nobody."""
    block = {"sahyadri": 6, "suryoday": 7, "kavach": 8}[agency_key]
    return f"+91 00000 {block}{number % 10000:04d}"


def new_lead(world_agency: Agency, day: date, index: int, *, cold: bool = False) -> Lead:
    rng = _rng(WORLD_VERSION, world_agency.key, day.isoformat(), index, cold)
    sellers = [s for s in world_agency.sellers if s.cold_only == cold] or list(world_agency.sellers)
    sales_personas = [(p, p.weight) for p in world_agency.personas if p.sales]
    persona = _pick(rng, sales_personas)
    arc = _pick(rng, list((COLD_WEIGHTS if cold else ARC_WEIGHTS).items()))
    number = int(day.strftime("%j")) * 40 + index + (5000 if cold else 0)
    return Lead(
        key=f"{world_agency.key}-{day:%m%d}-{'c' if cold else 'i'}{index:02d}",
        agency=world_agency.key,
        name=f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
        phone=_lead_phone(world_agency.key, number),
        source="cold_list" if cold else _pick(rng, world_agency.sources),
        persona=persona.key,
        product=rng.choice(world_agency.products).key,
        language=_pick(rng, world_agency.languages),
        seller=rng.choice(sellers).key,
        arc=arc,
        created=day.isoformat(),
        next_due=day.isoformat(),
    )


@dataclass
class PlannedCall:
    agency: str
    seller: str
    lead: str | None
    kind: str
    start: str  # ISO, India time
    seconds: int
    connected: bool
    sales: bool
    purpose: str
    language: str
    brief: str
    analyse: bool = False


def _slots(
    world_agency: Agency, day: date, seconds: Sequence[int], rng: random.Random
) -> list[datetime]:
    """Starts for one seller's calls, in order: spread over the working day with some jitter,
    never during lunch, never overlapping (90 s between calls), each ending before work ends."""
    start = datetime.combine(day, world_agency.start, IST)
    end = datetime.combine(day, world_agency.end, IST)
    lunch = (
        datetime.combine(day, world_agency.lunch[0], IST),
        datetime.combine(day, world_agency.lunch[1], IST),
    )
    working = (end - start) - (lunch[1] - lunch[0])
    step = working / max(1, len(seconds))
    out: list[datetime] = []
    cursor = start
    for index, length in enumerate(seconds):
        offset = step * index + timedelta(seconds=rng.uniform(0, step.total_seconds() / 3))
        moment = start + offset
        if moment >= lunch[0]:
            moment += lunch[1] - lunch[0]
        moment = max(moment, cursor)
        if moment < lunch[1] and moment + timedelta(seconds=length) > lunch[0]:
            moment = lunch[1]
        if moment + timedelta(seconds=length) > end:
            raise ValueError(f"{world_agency.key}: the calls don't fit in the working day")
        out.append(moment.replace(microsecond=0))
        cursor = moment + timedelta(seconds=length + 90)
    return out


def _brief(world_agency: Agency, lead: Lead, kind: str, seller: Person) -> str:
    product = next(p for p in world_agency.products if p.key == lead.product)
    persona = next(p for p in world_agency.personas if p.key == lead.persona)
    told = "; ".join(f"{h['day']}: {h['kind']}" for h in lead.history[-3:]) or "first contact"
    return (
        f"{world_agency.name} ({world_agency.city}, {world_agency.trade}). Seller {seller.name}, {seller.role}: "
        f"strong at {seller.strength}; weakness to show: {seller.weakness}. Other side: {lead.name}, {persona.who}, "
        f"from {lead.source}, about {product.name} ({product.price}). Call: {kind.replace('_', ' ')}. "
        f"Language: {lead.language}. Story so far: {told}."
    )


def plan_day(
    leads: list[Lead],
    day: date,
    *,
    agencies: Sequence[Agency] = AGENCIES,
    analyse_per_agency: int = 3,
) -> tuple[list[PlannedCall], list[Lead]]:
    """The day's calls for every agency, and the leads that arrived. ``leads`` is the saved
    state; it is advanced in place (story steps, next due day, history). Sunday plays nothing."""
    calls: list[PlannedCall] = []
    arrived: list[Lead] = []
    for world_agency in agencies:
        if day.weekday() not in world_agency.days:
            continue
        rng = _rng(WORLD_VERSION, world_agency.key, day.isoformat(), "day")
        count = rng.randint(*world_agency.leads_per_day)
        fresh = [new_lead(world_agency, day, i) for i in range(count)]
        cold_sellers = [s for s in world_agency.sellers if s.cold_only]
        if cold_sellers:
            fresh += [new_lead(world_agency, day, i, cold=True) for i in range(rng.randint(15, 25))]
        arrived.extend(fresh)
        leads.extend(fresh)
        sellers = {s.key: s for s in world_agency.sellers}
        due = [
            lead
            for lead in leads
            if lead.agency == world_agency.key and lead.next_due == day.isoformat()
        ]
        agency_calls: list[PlannedCall] = []
        for lead in due:
            steps = ARCS[lead.arc]
            if lead.step >= len(steps):
                lead.next_due = None
                continue
            kind, _ = steps[lead.step]
            seller = sellers.get(lead.seller) or world_agency.sellers[0]
            connected = kind != "no_answer" and (
                rng.random() < 0.85
                if kind != "cold_opener"
                else rng.random() < world_agency.connect_rate
            )
            low, high = LENGTHS[kind]
            seconds = rng.randint(low, high) if connected and high else 0
            agency_calls.append(
                PlannedCall(
                    world_agency.key,
                    seller.key,
                    lead.key,
                    kind,
                    "",
                    seconds,
                    connected,
                    True,
                    "sales",
                    lead.language,
                    _brief(world_agency, lead, kind, seller),
                )
            )
            lead.history.append(
                {"day": day.isoformat(), "kind": kind, "connected": connected, "seconds": seconds}
            )
            lead.step += 1
            if lead.step < len(steps):
                lead.next_due = (day + timedelta(days=max(1, steps[lead.step][1]))).isoformat()
            else:
                lead.next_due = None
        # Not-sales calls: about 15% of the connected ones.
        connected_n = sum(1 for c in agency_calls if c.connected)
        others = [
            (p, p.weight) for p in (*NOT_SALES, *(p for p in world_agency.personas if not p.sales))
        ]
        for _ in range(max(1, round(connected_n * 0.15))):
            persona = _pick(rng, others)
            seller = rng.choice(world_agency.sellers)
            low, high = LENGTHS["not_sales"]
            seconds = 65 if persona.key == "silence" else rng.randint(low, high)
            agency_calls.append(
                PlannedCall(
                    world_agency.key,
                    seller.key,
                    None,
                    f"not_sales:{persona.key}",
                    "",
                    seconds,
                    True,
                    False,
                    persona.purpose,
                    _pick(rng, world_agency.languages),
                    f"{world_agency.name}: {persona.who}; seller {seller.name}.",
                )
            )
        # Times inside work hours, never two calls at once for one seller.
        by_seller: dict[str, list[PlannedCall]] = {}
        for call in agency_calls:
            by_seller.setdefault(call.seller, []).append(call)
        for seller_key, own in by_seller.items():
            order = _rng(world_agency.key, day.isoformat(), seller_key, "order")
            order.shuffle(own)
            starts = _slots(
                world_agency,
                day,
                [c.seconds for c in own],
                _rng(world_agency.key, day.isoformat(), seller_key),
            )
            for call, moment in zip(own, starts, strict=True):
                call.start = moment.isoformat()
        # The day's analysed calls (they cost real analysis): one not-sales call when there is
        # one, then story calls before cold openers.
        connected_calls = [c for c in agency_calls if c.connected and c.seconds >= 20]
        rng.shuffle(connected_calls)
        not_sales = [c for c in connected_calls if not c.sales][:1]
        sales = sorted(
            (c for c in connected_calls if c.sales), key=lambda c: c.kind == "cold_opener"
        )
        for call in (not_sales + sales)[:analyse_per_agency]:
            call.analyse = True
        calls.extend(agency_calls)
    calls.sort(key=lambda c: (c.agency, c.start))
    return calls, arrived


def summary(calls: Sequence[PlannedCall]) -> dict[str, Any]:
    by: dict[str, dict[str, int]] = {}
    for call in calls:
        row = by.setdefault(
            call.agency,
            {"calls": 0, "connected": 0, "not_sales": 0, "analysed": 0, "talk_seconds": 0},
        )
        row["calls"] += 1
        row["connected"] += int(call.connected)
        row["not_sales"] += int(not call.sales)
        row["analysed"] += int(call.analyse)
        row["talk_seconds"] += call.seconds
    return by


def dump(leads: Sequence[Lead]) -> list[dict[str, Any]]:
    return [asdict(lead) for lead in leads]


def load(rows: Sequence[Mapping[str, Any]]) -> list[Lead]:
    return [Lead(**dict(row)) for row in rows]
