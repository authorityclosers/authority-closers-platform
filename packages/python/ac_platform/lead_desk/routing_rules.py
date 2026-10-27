"""Routing rules, saved and used (owner, 27 Oct 2026: lead rules should be "smarter, more
intelligent"; the leads setup audit found ``routing.py`` built but never wired).

A rule says **when** a new lead matches all its conditions, **give it to** one person or a
group in turn, within their limits. Conditions read what a lead carries: its source (Google
Ads lead forms apart from website forms), city, language, product, one form answer, or its
value: the answer the organisation names as the value, read as a rupee band ("₹60,000 –
₹1,00,000", "2L+"). Rules are tried top to bottom, and the first that can give the lead out
does; a rule whose people are all away or at their limit is passed over, and the lead's
reason says so. A lead no rule gives out goes by the lead rules as before (``allocation``).
A returning lead still goes back to its seller first.

The rules live in the workspace's Lead Desk settings (``routing_rules``, under the same
revision as the other settings). ``routing.py`` decides; this module stores, checks, reads
a lead's facts and answers the API (journey/http.py):

    GET  /v1/lead-desk/routing-rules        the rules, the sources, the sellers
    PUT  /v1/lead-desk/routing-rules        replace them all (expected_revision)
    POST /v1/lead-desk/routing-rules/try    where a lead like this would go now, and why
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from ac_platform.lead_desk import routing
from ac_platform.lead_desk.contracts import SCHEMA, Command, Model
from ac_platform.lead_desk.facets import facets, value_band
from ac_platform.lead_desk.journey import pipelines

KEY = "routing_rules"
VALUE_KEY = "routing_value_answer"
MAX_RULES = 30
GOOGLE_ADS_LABEL = "Google Ads"


class Condition(Model):
    """One test on a new lead. ``source``, ``city``, ``language`` and ``interest`` match any
    of ``values``; ``answer`` matches the form answer ``key`` against ``values``; ``value``
    compares the lead's value band (``op`` with ``low`` and/or ``high``, in rupees)."""

    field: Literal["source", "city", "language", "interest", "answer", "value"]
    values: tuple[str, ...] = Field(default=(), max_length=20)
    key: str | None = Field(default=None, max_length=80)
    op: Literal["at_least", "below", "between"] | None = None
    low: int | None = Field(default=None, ge=0)
    high: int | None = Field(default=None, ge=0)

    @field_validator("values")
    @classmethod
    def _clean(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(" ".join(value.split())[:120] for value in values if value.strip())

    @model_validator(mode="after")
    def _complete(self) -> Condition:
        if self.field == "value":
            needs = {
                "at_least": (self.low,),
                "below": (self.high,),
                "between": (self.low, self.high),
            }
            if self.op is None or any(item is None for item in needs[self.op]):
                raise ValueError("Give the value's amount.")
            if self.op == "between" and (self.low or 0) > (self.high or 0):
                raise ValueError("The lower amount comes first.")
            return self
        if not self.values:
            raise ValueError("Pick at least one value for each condition.")
        if self.field == "answer" and not (self.key or "").strip():
            raise ValueError("Pick the form question.")
        if self.field == "source" and any(value not in pipelines.SOURCES for value in self.values):
            raise ValueError("Pick the lead sources from the list.")
        return self


class Rule(Model):
    id: str | None = Field(default=None, max_length=40)
    name: str = Field(default="", max_length=60)
    enabled: bool = True
    when: tuple[Condition, ...] = Field(min_length=1, max_length=6)
    # One person, or a group taking turns in this order.
    give_to: tuple[UUID, ...] = Field(min_length=1, max_length=30)


class RoutingCommand(Command):
    expected_revision: int = Field(ge=0)
    rules: tuple[Rule, ...] = Field(default=(), max_length=MAX_RULES)
    # The form question whose answer is a lead's value (a facet key); None: no value rules.
    value_answer: str | None = Field(default=None, max_length=80)


class Person(Model):
    person_id: UUID
    name: str
    available: bool
    open_leads: int
    max_open: int | None


class Question(Model):
    """A form question recent leads answered (a facet key), for an "answer is" condition
    or as the value answer, with a few of its answers."""

    key: str
    label: str
    answered: int
    examples: tuple[str, ...]


class RoutingView(Model):
    schema_: Literal["lead-desk/1"] = Field(SCHEMA, alias="schema")
    revision: int
    rules: tuple[Rule, ...]
    value_answer: str | None
    # Sources a condition can name, with their words (Lead stages uses the same list).
    sources: dict[str, str]
    # Sellers a rule can give leads to; a rule naming someone no longer here passes them by.
    people: tuple[Person, ...]
    # What recent leads' forms asked, most answered first.
    questions: tuple[Question, ...] = ()
    can_edit: bool


class TryLead(Model):
    """A made-up new lead: where it would go now, and why (nothing is saved)."""

    source: str | None = Field(default=None, max_length=40)
    city: str | None = Field(default=None, max_length=120)
    language: str | None = Field(default=None, max_length=40)
    interest: str | None = Field(default=None, max_length=200)
    value: str | None = Field(default=None, max_length=80)
    answers: dict[str, str] = Field(default_factory=dict, max_length=30)


class TryView(Model):
    person_id: UUID | None
    name: str | None
    # 1 for the first rule; None when the lead rules would decide.
    rule: int | None
    rule_name: str | None
    why: str
    passed_over: tuple[str, ...] = ()


def stored(config: Mapping[str, Any]) -> tuple[Rule, ...]:
    """The saved rules, read leniently: a rule that no longer reads is left out."""
    found: list[Rule] = []
    for item in config.get(KEY) or ():
        try:
            found.append(Rule.model_validate(item))
        except ValueError:
            continue
    return tuple(found)


def pure(rules: Iterable[Rule]) -> tuple[tuple[Rule, routing.Rule], ...]:
    """The switched-on rules, as ``routing.py`` decides with them."""
    made: list[tuple[Rule, routing.Rule]] = []
    for rule in rules:
        if not rule.enabled:
            continue
        conditions: list[routing.Condition] = []
        for item in rule.when:
            if item.field == "value" and item.op is not None:
                conditions.append(routing.ValueIs(item.op, low=item.low, high=item.high))
            elif item.field == "answer" and item.key:
                conditions.append(routing.AnswerIn(item.key, item.values))
            elif item.field in {"source", "city", "language", "interest"}:
                conditions.append(routing.FieldIn(item.field, item.values))
        made.append((rule, routing.Rule(tuple(conditions), rule.give_to)))
    return tuple(made)


def lead_source(source: str | None, label: str | None) -> str | None:
    """A lead's source as a condition reads it: Google Ads lead forms apart from forms."""
    if source == "webhook" and (label or "").startswith(GOOGLE_ADS_LABEL):
        return "google_ads"
    return source


def facts(
    *,
    source: str | None,
    source_label: str | None = None,
    city: str | None,
    language: str | None,
    interest: str | None,
    payload: Mapping[str, Any] | None,
    value_answer: str | None,
    value: str | None = None,
) -> routing.LeadFacts:
    """What a rule reads of a lead: never its name, number or free text."""
    answers = {item.key: item.value for item in facets(payload or {})}
    raw = value if value is not None else (answers.get(value_answer) if value_answer else None)
    return routing.LeadFacts(
        value=value_band(raw) if raw else None,
        answers=answers,
        source=lead_source(source, source_label),
        city=city,
        language=language,
        interest=interest,
    )


def seats(people: Sequence[Any], exclude: Iterable[UUID] = ()) -> tuple[routing.Seat, ...]:
    """The team as rules see it; someone excluded (the lead's current owner) has no room."""
    out = frozenset(exclude)
    return tuple(
        routing.Seat(
            person_id=state.person_id,
            name=state.name,
            available=state.available and state.person_id not in out,
            open_leads=state.open_leads,
            cap=state.max_open,
            last_given_at=state.last_assigned_at,
        )
        for state in people
    )


def decide(
    config: Mapping[str, Any], lead_facts: routing.LeadFacts, team: Sequence[routing.Seat]
) -> tuple[routing.Decision, str | None] | None:
    """The routing decision for a lead, with the rule's name; None when no rule is on."""
    rules = pure(stored(config))
    if not rules:
        return None
    decision = routing.decide(lead_facts, [rule for _, rule in rules], team)
    name = rules[decision.rule - 1][0].name if decision.rule else None
    return decision, name


def questions(payloads: Iterable[Mapping[str, Any] | None]) -> tuple[Question, ...]:
    """The form questions in these leads' answers, most answered first, with up to six of
    their most common answers each (choices only: ``facets`` leaves out free text)."""
    labels: dict[str, str] = {}
    answered: Counter[str] = Counter()
    answers: dict[str, Counter[str]] = {}
    for payload in payloads:
        for item in facets(payload or {}):
            labels.setdefault(item.key, item.label)
            answered[item.key] += 1
            answers.setdefault(item.key, Counter())[item.value] += 1
    return tuple(
        Question(
            key=key,
            label=labels[key],
            answered=count,
            examples=tuple(value for value, _ in answers[key].most_common(6)),
        )
        for key, count in answered.most_common(30)
    )


def view(
    config: Mapping[str, Any],
    revision: int,
    people: Sequence[Any],
    *,
    questions: Sequence[Question] = (),
    can_edit: bool,
) -> RoutingView:
    return RoutingView(
        revision=revision,
        rules=stored(config),
        value_answer=config.get(VALUE_KEY),
        sources=dict(pipelines.SOURCES),
        people=tuple(
            Person(
                person_id=state.person_id,
                name=state.name,
                available=state.available,
                open_leads=state.open_leads,
                max_open=state.max_open,
            )
            for state in people
        ),
        questions=tuple(questions),
        can_edit=can_edit,
    )


def saved(command: RoutingCommand, people: Iterable[UUID]) -> dict[str, Any]:
    """The rules as stored: every rule with an id, and only sellers of this workspace."""
    known = frozenset(people)
    rules: list[dict[str, Any]] = []
    for rule in command.rules:
        strangers = [person for person in rule.give_to if person not in known]
        if strangers:
            raise ValueError("A rule names someone who isn't a seller here. Reload the page.")
        rules.append(
            rule.model_copy(update={"id": rule.id or uuid4().hex[:12]}).model_dump(mode="json")
        )
    return {KEY: rules, VALUE_KEY: (command.value_answer or "").strip() or None}


__all__ = [
    "KEY",
    "VALUE_KEY",
    "Condition",
    "Person",
    "Question",
    "Rule",
    "RoutingCommand",
    "RoutingView",
    "TryLead",
    "TryView",
    "decide",
    "facts",
    "lead_source",
    "questions",
    "saved",
    "seats",
    "stored",
    "view",
]
