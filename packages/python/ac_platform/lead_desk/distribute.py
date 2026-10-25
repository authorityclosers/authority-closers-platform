"""Distribution: a manager assigns a chosen set of leads by a rule (team engine, section 1;
docs/product/lead-desk/team-engine.md).

Rules:
- ``even``: round-robin over the chosen sellers; each lead goes to whoever has the fewest
  from this distribution so far, ties by the sellers' order. Any two sellers under cap end
  within one lead of each other.
- ``balanced``: the same, counted on open leads after the move, so the lighter catch up.
- ``by_source`` / ``by_city``: each source or city maps to one or more sellers and is spread
  evenly over them; a lead whose source or city has no seller stays where it is.

A seller at their open-lead cap takes no more; what nobody can take stays put and is counted
with why. Closed leads (Won, Lost, Junk) never move. Under ``even`` and ``balanced`` a lead
already with one of the chosen sellers stays, unless ``spread_all`` is set.

Pure: leads, sellers and a rule in; a plan out. No database, no clock, no randomness.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal
from uuid import UUID

Rule = Literal["even", "balanced", "by_source", "by_city"]
RULES: Final[tuple[Rule, ...]] = ("even", "balanced", "by_source", "by_city")
CLOSED: Final = frozenset({"won", "lost", "junk"})
LIMIT: Final = 1000

RULE_WORDS: Final[dict[Rule, str]] = {
    "even": "Even",
    "balanced": "Balanced",
    "by_source": "By source",
    "by_city": "By city",
}


@dataclass(frozen=True, slots=True)
class LeadSpot:
    """What distribution needs of a lead."""

    lead_id: UUID
    stage: str
    owner: UUID | None = None
    source: str | None = None
    city: str | None = None


@dataclass(frozen=True, slots=True)
class Seller:
    person_id: UUID
    open_leads: int
    # None: no limit.
    max_open: int | None


@dataclass(frozen=True, slots=True)
class Move:
    lead_id: UUID
    to: UUID
    previous: UUID | None


@dataclass(frozen=True, slots=True)
class Plan:
    moves: tuple[Move, ...]
    # Per seller: how many leads this distribution gives them.
    given: Mapping[UUID, int]
    # Leads left where they are, by why: "closed", "already_theirs", "no_seller_for_it",
    # "everyone_at_cap".
    left: Mapping[str, int] = field(default_factory=dict)


def _key(value: str | None) -> str:
    return " ".join((value or "").lower().split())


def distribute(
    leads: Sequence[LeadSpot],
    sellers: Sequence[Seller],
    rule: Rule,
    *,
    groups: Mapping[str, Sequence[UUID]] | None = None,
    spread_all: bool = False,
) -> Plan:
    """The plan for these leads, in their given order, over these sellers in theirs."""
    if rule not in RULES:
        raise ValueError(f"Unknown rule: {rule}")
    if len(leads) > LIMIT:
        raise ValueError(f"At most {LIMIT} leads at a time.")
    order = {seller.person_id: index for index, seller in enumerate(sellers)}
    by_id = {seller.person_id: seller for seller in sellers}
    given: Counter[UUID] = Counter()
    # Open leads each seller holds as the plan goes (caps, and the balanced rule).
    holds: dict[UUID, int] = {seller.person_id: seller.open_leads for seller in sellers}
    left: Counter[str] = Counter()
    moves: list[Move] = []
    keyed = {_key(name): list(people) for name, people in (groups or {}).items()}

    def room(person: UUID) -> bool:
        cap = by_id[person].max_open
        return cap is None or holds[person] < cap

    def pick(pool: Sequence[UUID]) -> UUID | None:
        open_pool = [person for person in pool if person in by_id and room(person)]
        if not open_pool:
            return None
        if rule == "balanced":
            return min(open_pool, key=lambda person: (holds[person], order[person]))
        return min(open_pool, key=lambda person: (given[person], order[person]))

    for lead in leads:
        if lead.stage in CLOSED:
            left["closed"] += 1
            continue
        if rule in ("by_source", "by_city"):
            wanted = keyed.get(_key(lead.source if rule == "by_source" else lead.city), [])
            if not wanted:
                left["no_seller_for_it"] += 1
                continue
            pool: Sequence[UUID] = wanted
        else:
            pool = list(order)
            if lead.owner in order and not spread_all:
                left["already_theirs"] += 1
                continue
        if lead.owner is not None and lead.owner in pool and not spread_all:
            left["already_theirs"] += 1
            continue
        if lead.owner in holds:
            # Spreading everything: its own seller is counted as if it were free of it.
            holds[lead.owner] -= 1
        chosen = pick(pool)
        if chosen is None:
            if lead.owner in holds:
                holds[lead.owner] += 1
            left["everyone_at_cap"] += 1
            continue
        given[chosen] += 1
        holds[chosen] += 1
        if chosen != lead.owner:
            moves.append(Move(lead.lead_id, chosen, lead.owner))
    return Plan(moves=tuple(moves), given=dict(given), left=dict(left))
