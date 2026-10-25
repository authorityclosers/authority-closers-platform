"""Dynamic lead allocation: a fair owner by rules and current load, never random.

15 Oct sync: allocation must be dynamic, "not a random function that leaves
10 people idle". The rules, in order:

1. Who can take it: available now, under their open-lead cap, and (when the
   lead says) speaks its language, covers its area and sells its product.
   A rep with no languages, areas or products set is not limited by them.
2. A returning lead goes back to the seller who handled it before, when that
   seller can still take it.
3. Otherwise the fewest open leads wins; ties go to whoever waited longest
   since their last new lead, then by name.
4. When nobody fits every rule, product then area are relaxed (never
   language first: a lead the seller can't talk to is wasted), and the reason
   says so. When nobody is available or under cap, the lead waits unassigned
   for a manager.

Every decision returns a short reason in plain words; the caller stores it on
the lead and in its history. This module is pure: no database, no clock.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RepState:
    person_id: UUID
    name: str
    available: bool
    # None: no limit.
    max_open: int | None
    open_leads: int
    languages: tuple[str, ...] = ()
    areas: tuple[str, ...] = ()
    interests: tuple[str, ...] = ()
    last_assigned_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class LeadFacts:
    language: str | None = None
    city: str | None = None
    interest: str | None = None
    previous_owner: UUID | None = None
    exclude: frozenset[UUID] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class Allocation:
    person_id: UUID | None
    reason: str
    rule: str


def _norm(value: str) -> str:
    return " ".join(value.lower().replace("-", " ").split())


def _matches(wanted: str | None, offered: Iterable[str]) -> bool | None:
    """None: the rule doesn't apply (no value on the lead or no limit on the rep)."""
    offered = tuple(_norm(item) for item in offered if item and item.strip())
    if not wanted or not wanted.strip() or not offered:
        return None
    target = _norm(wanted)
    return any(item == target or item in target or target in item for item in offered)


def _language_matches(wanted: str | None, spoken: Iterable[str]) -> bool | None:
    spoken = tuple(spoken)
    if not wanted or not spoken:
        return None
    # "Hindi, English" or "hi-mr-en" style values: any shared language counts.
    parts = [p for p in _norm(wanted).replace(",", " ").replace("/", " ").split() if p]
    known = {_norm(item) for item in spoken}
    codes = {_CODES.get(item, item) for item in known} | known
    return any(part in codes or _CODES.get(part, part) in codes for part in parts)


_CODES = {
    "english": "en",
    "hindi": "hi",
    "marathi": "mr",
    "gujarati": "gu",
    "tamil": "ta",
    "telugu": "te",
    "kannada": "kn",
    "malayalam": "ml",
    "bengali": "bn",
    "bangla": "bn",
    "punjabi": "pa",
    "odia": "or",
    "urdu": "ur",
}


def _sort_key(rep: RepState) -> tuple[int, float, str]:
    waited = rep.last_assigned_at.timestamp() if rep.last_assigned_at else float("-inf")
    return (rep.open_leads, waited, rep.name.lower())


def _load(rep: RepState) -> str:
    return f"{rep.open_leads} open lead{'s' if rep.open_leads != 1 else ''}"


def allocate(lead: LeadFacts, reps: Sequence[RepState]) -> Allocation:
    candidates = [
        rep
        for rep in reps
        if rep.person_id not in lead.exclude
        and rep.available
        and (rep.max_open is None or rep.open_leads < rep.max_open)
    ]
    if not candidates:
        if not any(rep.available for rep in reps if rep.person_id not in lead.exclude):
            return Allocation(
                None, "Nobody is available right now; it waits for a manager.", "none"
            )
        return Allocation(
            None, "Everyone available is at their open-lead limit; it waits for a manager.", "none"
        )

    def fits(rep: RepState, *, area: bool, product: bool) -> bool:
        checks = [_language_matches(lead.language, rep.languages)]
        if area:
            checks.append(_matches(lead.city, rep.areas))
        if product:
            checks.append(_matches(lead.interest, rep.interests))
        return all(check is not False for check in checks)

    if lead.previous_owner is not None:
        previous = next((rep for rep in candidates if rep.person_id == lead.previous_owner), None)
        if previous is not None and fits(previous, area=False, product=False):
            return Allocation(
                previous.person_id,
                f"Returning lead: back to {previous.name}, who handled it before.",
                "returning",
            )

    for area, product, note in (
        (True, True, ""),
        (True, False, "nobody free sells this product, "),
        (False, False, "nobody free covers this area, "),
    ):
        pool = [rep for rep in candidates if fits(rep, area=area, product=product)]
        if pool:
            chosen = min(pool, key=_sort_key)
            parts: list[str] = []
            if _language_matches(lead.language, chosen.languages):
                parts.append(f"speaks {lead.language}")
            if area and _matches(lead.city, chosen.areas):
                parts.append(f"covers {lead.city}")
            if product and _matches(lead.interest, chosen.interests):
                parts.append(f"sells {lead.interest}")
            fewest = len(pool) > 1 and all(
                chosen.open_leads <= rep.open_leads for rep in pool if rep is not chosen
            )
            load = _load(chosen) + (" (fewest)" if fewest else "")
            text = note + ", ".join([*parts, load])
            return Allocation(
                chosen.person_id, text[:1].upper() + text[1:], "relaxed" if note else "rules"
            )

    # Nobody speaks the lead's language: give it to the least-loaded free seller
    # and say so, rather than leaving the lead to go cold.
    chosen = min(candidates, key=_sort_key)
    return Allocation(
        chosen.person_id,
        f"Nobody free speaks {lead.language}; {_load(chosen)}, the fewest.",
        "language_gap",
    )
