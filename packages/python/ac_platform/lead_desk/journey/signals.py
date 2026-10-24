"""Stage suggestions from what the business's calls and notes already say. Offers only.

- **Stages for the business.** The agreed next steps and outcomes the call analysis
  found (fast and deep pipelines, ``call_objects``), and the sellers' own notes, are read
  for sales moments ("visit the site on Saturday", "sent the quote"). A moment heard
  in at least three calls or notes that no stage covers is offered as a stage, named
  from the words heard most ("Site visit booked"). A manager adds it with a tap.
- **A next stage for one lead.** The lead's newest call facts say where it got to; when
  that is further along than its stage, the lead's sheet can offer the move with the
  words that suggest it. A person confirms it; nothing moves by itself.

Only facts the call analysis already keeps for this organisation are read; nothing
leaves Sales Xray and nothing here is stored.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.call_data.models import CallObject
from ac_platform.lead_desk.journey.model import Journey, Stage, funnel_rank
from ac_platform.lead_desk.journey.templates import (
    KIND_WORDS,
    MILESTONE_KIND,
    MILESTONE_WORDS,
    guess_milestone,
)
from ac_platform.lead_desk.models import LeadEvent

SIGNAL_TYPES: Final[tuple[str, ...]] = (
    "commitment.next_step",
    "commitment.follow_up",
    "outcome.call_outcome",
)
OUTCOMES: Final[dict[str, str]] = {
    "meeting_scheduled": "appointment_booked",
    "deal_closed": "won",
    "follow_up_agreed": "contacted",
    "callback_requested": "contacted",
}
LOOK_BACK: Final[timedelta] = timedelta(days=90)
READ_LIMIT: Final[int] = 2000
MIN_HEARD: Final[int] = 3
# The thing met or visited, as people say it; the longest wins.
_TERM: Final[re.Pattern[str]] = re.compile(
    r"(site visit|site survey|test drive|demo class|trial class|home visit|store visit|"
    r"showroom visit|clinic visit|consultation|demo|appointment|meeting|inspection|"
    r"walk-?in|survey|visit)"
)
_PLAIN: Final[dict[str, str]] = {
    "proposal": "Quote sent",
    "application": "Documents collected",
    "negotiation": "Negotiation",
    "qualified": "Qualified",
    "contacted": "Contacted",
}


def milestone_of(type_key: str, value: Any, display: str | None) -> str | None:
    """The sales moment one call fact or note points at, or None."""
    if type_key == "outcome.call_outcome":
        found = value.get("value") if isinstance(value, Mapping) else value
        return OUTCOMES.get(str(found)) if found else None
    text = (display or "").strip()
    if not text:
        return None
    milestone = guess_milestone(text)
    return None if milestone in ("other", "lead", "unreachable", "lost") else milestone


def term_of(text: str) -> str | None:
    found = _TERM.findall(text.lower())
    return max(found, key=len) if found else None


def label_for(milestone: str, term: str | None) -> str:
    if milestone in ("appointment_booked", "appointment_done") and term:
        word = term.replace("-", " ").strip()
        word = word[:1].upper() + word[1:]
        return f"{word} {'booked' if milestone == 'appointment_booked' else 'done'}"
    if milestone == "appointment_booked":
        return "Meeting booked"
    if milestone == "appointment_done":
        return "Meeting done"
    return _PLAIN.get(milestone, MILESTONE_WORDS.get(milestone, "New stage"))


def _note(data: Any) -> str | None:
    if not isinstance(data, Mapping):
        return None
    text = data.get("remark") or data.get("note")
    return str(text)[:400] if isinstance(text, str) and text.strip() else None


async def heard(
    db: AsyncSession, tenant_id: UUID, now: datetime
) -> tuple[Counter[str], dict[str, Counter[str]]]:
    """How often each sales moment came up lately, and the words used for it."""
    since = now - LOOK_BACK
    counts: Counter[str] = Counter()
    terms: dict[str, Counter[str]] = {}

    def count(milestone: str | None, text: str | None) -> None:
        if milestone is None:
            return
        counts[milestone] += 1
        term = term_of(text or "")
        if term:
            terms.setdefault(milestone, Counter())[term] += 1

    facts = await db.execute(
        select(CallObject.type_key, CallObject.value, CallObject.display)
        .where(
            CallObject.tenant_id == tenant_id,
            CallObject.type_key.in_(SIGNAL_TYPES),
            CallObject.retracted.is_(False),
            CallObject.erased_at.is_(None),
            CallObject.created_at >= since,
        )
        .order_by(CallObject.created_at.desc())
        .limit(READ_LIMIT)
    )
    for type_key, value, display in facts.tuples():
        count(milestone_of(type_key, value, display), display)
    notes = await db.execute(
        select(LeadEvent.data)
        .where(
            LeadEvent.tenant_id == tenant_id,
            LeadEvent.kind.in_(("result", "note", "stage")),
            LeadEvent.created_at >= since,
        )
        .order_by(LeadEvent.created_at.desc())
        .limit(READ_LIMIT)
    )
    for (data,) in notes.tuples():
        text = _note(data)
        count(milestone_of("note", None, text), text)
    return counts, terms


def business_suggestions(
    counts: Counter[str], terms: Mapping[str, Counter[str]], journey: Journey
) -> list[dict[str, Any]]:
    """Moments heard often that no live stage covers, as stages to add."""
    covered = {stage.milestone for stage in journey.live}
    names = {stage.label.casefold() for stage in journey.live}
    out = []
    for milestone, times in counts.most_common():
        if times < MIN_HEARD or milestone in covered or milestone in ("won", "contacted"):
            continue
        top = terms.get(milestone)
        label = label_for(milestone, top.most_common(1)[0][0] if top else None)
        if label.casefold() in names:
            continue
        kind = MILESTONE_KIND[milestone]
        out.append(
            {
                "ref": f"calls:{milestone}",
                "label": label,
                "source": "your calls",
                "workflow": f"heard in {times} calls and notes",
                "milestone": milestone,
                "meaning": MILESTONE_WORDS[milestone],
                "kind": kind,
                "kindWords": KIND_WORDS[kind],
            }
        )
    return out[:4]


def _ahead(journey: Journey, current: Stage | None, target: Stage) -> bool:
    if current is None or current.key == target.key:
        return current is None
    if target.kind == "won":
        return current.kind not in ("won", "lost", "junk")
    keys = [stage.key for stage in journey.funnel()]
    if current.key in keys and target.key in keys:
        return keys.index(target.key) > keys.index(current.key)
    return funnel_rank(target) > funnel_rank(current)


async def lead_suggestion(
    db: AsyncSession,
    tenant_id: UUID,
    lead_id: UUID,
    kind: str,
    step: str | None,
    journey: Journey,
) -> dict[str, Any] | None:
    """Where the lead's newest call says it got to, when that is further than its stage."""
    rows = await db.execute(
        select(CallObject.type_key, CallObject.value, CallObject.display, CallObject.created_at)
        .where(
            CallObject.tenant_id == tenant_id,
            CallObject.lead_id == lead_id,
            CallObject.type_key.in_(SIGNAL_TYPES),
            CallObject.retracted.is_(False),
            CallObject.erased_at.is_(None),
        )
        .order_by(CallObject.created_at.desc())
        .limit(20)
    )
    current = journey.resolve(kind, step)
    for type_key, value, display, at in rows.tuples():
        milestone = milestone_of(type_key, value, display)
        if milestone is None:
            continue
        target = next((stage for stage in journey.live if stage.milestone == milestone), None)
        if target is None or not _ahead(journey, current, target):
            continue
        if current is not None and current.moves is not None and target.key not in current.moves:
            continue  # not a move this stage list allows (Lead OS)
        return {
            "step": target.key,
            "label": target.label,
            "kind": target.kind,
            "why": (display or MILESTONE_WORDS.get(milestone, ""))[:160],
            "at": at,
        }
    return None
