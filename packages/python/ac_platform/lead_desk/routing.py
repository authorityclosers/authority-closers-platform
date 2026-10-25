"""Routing rules: who gets a new lead, by its value, answers, source or place
(docs/product/lead-desk/routing-and-patterns.md, section 2). Pure: no database and no clock.

A rule is: **when** all its conditions hold, **give to** one person or a group (round-robin
inside it), **within** caps. Rules are tried top to bottom and the first that can give the lead
out does. A rule whose people are all away or at their cap is passed over, and the reason says
so; a lead no rule takes goes by the lead rules as before (``allocation``).

Value conditions read the lead's band with care: "at least X" needs its low to be X or more,
"below X" needs its high to be under X, "between" needs both inside. A lead with no value never
meets a value condition.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

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
        return given is not None and fold(given) in {fold(value) for value in self.values}

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


def matches(rule: Rule, facts: LeadFacts) -> bool:
    return bool(rule.conditions) and all(item.holds(facts) for item in rule.conditions)


def _turn(rule: Rule, seats: Mapping[UUID, Seat]) -> Seat | None:
    """The person in the rule whose turn it is: with room, given a lead longest ago."""
    order = {person: index for index, person in enumerate(rule.people)}
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


def decide(facts: LeadFacts, rules: Sequence[Rule], seats: Sequence[Seat]) -> Decision:
    by_person = {seat.person_id: seat for seat in seats}
    passed: list[str] = []
    for number, rule in enumerate(rules, start=1):
        if not matches(rule, facts):
            continue
        reason = "; ".join(item.words(facts) for item in rule.conditions)
        seat = _turn(rule, by_person)
        if seat is None:
            names = [by_person[p].name for p in rule.people if p in by_person] or ["nobody"]
            passed.append(f"Rule {number}: {', '.join(names)} away or at their limit")
            continue
        return Decision(
            seat.person_id, number, f"{reason}: {seat.name} (rule {number})", tuple(passed)
        )
    if passed:
        return Decision(None, None, f"{passed[-1]}, given by the lead rules", tuple(passed))
    return Decision(None, None, "No routing rule matched; given by the lead rules")
