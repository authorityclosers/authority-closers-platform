"""Routing rules: who gets a new lead, by its value, answers, source or place
(docs/product/lead-desk/routing-and-patterns.md, section 2). Pure: no database and no clock.

A rule is: **when** all its conditions hold, **give to** one person or a group (round-robin
inside it, or split by percent), **within** caps. Rules are tried top to bottom and the first
that can give the lead out does. A rule whose people are all away or at their cap is passed
over, and the reason says so; a lead no rule takes goes by the lead rules as before
(``allocation``).

A split rule (owner, Wise Life, 19 Nov 2026: "Dheeraj 20%, Aniket 40%, Sachin 40%") gives each
person a share. The next lead goes to whoever is furthest behind their share, counted over every
lead the rule has given out (``given``), so ten leads go 2/4/4 and the split holds over time.
Someone away or at their cap is skipped and catches up once back; a share of 0 never gets one.

Value conditions read the lead's band with care: "at least X" needs its low to be X or more,
"below X" needs its high to be under X, "between" needs both inside. A lead with no value never
meets a value condition.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction
from typing import Literal
from uuid import UUID

from ac_platform.lead_desk import allocation
from ac_platform.lead_desk.facets import Band, band_words, rupees

ValueOp = Literal["at_least", "below", "between"]
FieldName = Literal["source", "city", "language", "interest"]


def fold(text: str | None) -> str:
    return " ".join((text or "").lower().split())


@dataclass(frozen=True, slots=True)
class ValueIs:
    op: ValueOp
    low: int | None = None
    high: int | None = None

    def holds(self, facts: LeadFacts) -> bool:
        band = facts.value
        if band is None:
            return False
        if self.op == "at_least":
            return self.low is not None and band.low is not None and band.low >= self.low
        if self.op == "below":
            return self.high is not None and band.high is not None and band.high < self.high
        return (
            self.low is not None
            and self.high is not None
            and band.low is not None
            and band.high is not None
            and self.low <= band.low
            and band.high <= self.high
        )

    def words(self, facts: LeadFacts) -> str:
        shown = band_words(facts.value) if facts.value else "no value"
        if self.op == "at_least":
            return f"Value {shown} ≥ {rupees(self.low or 0)}"
        if self.op == "below":
            return f"Value {shown} < {rupees(self.high or 0)}"
        return f"Value {shown} within {rupees(self.low or 0)} – {rupees(self.high or 0)}"


@dataclass(frozen=True, slots=True)
class AnswerIn:
    key: str
    values: tuple[str, ...]

    def holds(self, facts: LeadFacts) -> bool:
        given = facts.answers.get(self.key)
        return given is not None and fold(given) in {fold(value) for value in self.values}

    def words(self, facts: LeadFacts) -> str:
        return f'"{facts.answers.get(self.key, "")}"'


@dataclass(frozen=True, slots=True)
class FieldIn:
    name: FieldName
    values: tuple[str, ...]

    def holds(self, facts: LeadFacts) -> bool:
        given = getattr(facts, self.name)
        if given is None:
            return False
        # The keys seller matching uses (lead_desk/choices.py offers chips by them), so a
        # picked chip matches here too: "Navi-Mumbai" is "Navi Mumbai", and a lead in
        # "Hindi, English" speaks Hindi.
        if self.name == "language":
            wanted = {code for value in self.values for code in allocation.language_codes(value)}
            return bool(wanted & set(allocation.language_codes(given)))
        if self.name in {"city", "interest"}:
            return allocation.key(given) in {allocation.key(value) for value in self.values}
        return fold(given) in {fold(value) for value in self.values}

    def words(self, facts: LeadFacts) -> str:
        return str(getattr(facts, self.name) or "")


Condition = ValueIs | AnswerIn | FieldIn


@dataclass(frozen=True, slots=True)
class LeadFacts:
    """What a rule reads of a new lead: never its name, number or free text."""

    value: Band | None = None
    answers: Mapping[str, str] = field(default_factory=dict)
    source: str | None = None
    city: str | None = None
    language: str | None = None
    interest: str | None = None


@dataclass(frozen=True, slots=True)
class Rule:
    conditions: tuple[Condition, ...]
    # One person, or a group taking turns in this order.
    people: tuple[UUID, ...]
    # A split by percent: one share per person, in ``people``'s order; () takes turns.
    shares: tuple[int, ...] = ()
    # The saved rule's id, which the split counts its leads by.
    key: str | None = None
    # For every new lead, with no conditions (a split of all leads).
    every: bool = False


@dataclass(frozen=True, slots=True)
class Seat:
    person_id: UUID
    name: str
    available: bool
    open_leads: int
    # None: no limit.
    cap: int | None
    last_given_at: datetime | None = None

    @property
    def has_room(self) -> bool:
        return self.available and (self.cap is None or self.open_leads < self.cap)


@dataclass(frozen=True, slots=True)
class Decision:
    person_id: UUID | None
    # 1 for the first rule; None when no rule gave the lead out.
    rule: int | None
    why: str
    passed_over: tuple[str, ...] = ()
    # The split rule's key when a split gave it out: its history line counts for the split.
    split: str | None = None


def matches(rule: Rule, facts: LeadFacts) -> bool:
    """A rule for every new lead always matches; any other needs all its conditions, and
    one with none never matches."""
    if rule.every:
        return True
    return bool(rule.conditions) and all(item.holds(facts) for item in rule.conditions)


def _turn(rule: Rule, seats: Mapping[UUID, Seat], given: Mapping[UUID, int]) -> Seat | None:
    """The person in the rule whose turn it is: with room, given a lead longest ago; in a
    split, the one furthest behind their share."""
    order = {person: index for index, person in enumerate(rule.people)}
    if rule.shares:
        share = dict(zip(rule.people, rule.shares, strict=False))
        ready = [
            seats[person]
            for person in rule.people
            if person in seats and seats[person].has_room and share.get(person, 0) > 0
        ]
        if not ready:
            return None
        # Furthest behind: the fewest leads per share after this one, then the bigger share,
        # then the rule's order. Exact (no floats): compare (given + 1) / share as a fraction.
        return min(
            ready,
            key=lambda seat: (
                Fraction(given.get(seat.person_id, 0) + 1, share[seat.person_id]),
                -share[seat.person_id],
                order[seat.person_id],
            ),
        )
    ready = [seats[person] for person in rule.people if person in seats and seats[person].has_room]
    if not ready:
        return None
    # Never given one first, then the longest ago, then the rule's order.
    return min(
        ready,
        key=lambda seat: (
            seat.last_given_at is not None,
            seat.last_given_at.timestamp() if seat.last_given_at else 0.0,
            order[seat.person_id],
        ),
    )


def decide(
    facts: LeadFacts,
    rules: Sequence[Rule],
    seats: Sequence[Seat],
    given: Mapping[str, Mapping[UUID, int]] | None = None,
) -> Decision:
    """``given``: per split rule's key, how many leads it has given each person so far."""
    by_person = {seat.person_id: seat for seat in seats}
    passed: list[str] = []
    for number, rule in enumerate(rules, start=1):
        if not matches(rule, facts):
            continue
        reason = "; ".join(item.words(facts) for item in rule.conditions) or "Every new lead"
        seat = _turn(rule, by_person, (given or {}).get(rule.key or "", {}))
        if seat is None:
            names = [by_person[p].name for p in rule.people if p in by_person] or ["nobody"]
            passed.append(f"Rule {number}: {', '.join(names)} away or at their limit")
            continue
        share = dict(zip(rule.people, rule.shares, strict=False)).get(seat.person_id)
        who = f"{seat.name}, {share}% share" if share else seat.name
        return Decision(
            seat.person_id,
            number,
            f"{reason}: {who} (rule {number})",
            tuple(passed),
            split=rule.key if rule.shares else None,
        )
    if passed:
        return Decision(None, None, f"{passed[-1]}, given by the lead rules", tuple(passed))
    return Decision(None, None, "No routing rule matched; given by the lead rules")
