"""Auto-reassign's guard rails (Wise Life's first day with it, 20 Nov 2026).

The 30-work-minute move (``LeadDesk.sweep``) went live on 20 Nov 17:15 IST and the day's
analysis found four faults. The rules here answer them:

- **Contacted stops the clock.** A lead counts as reached for on any of: a call tap from
  the app (its ``call`` line), a call the phone logged of ``CALL_SECONDS`` or more, a
  WhatsApp or SMS someone sent or opened from the app, a saved result, or a note by the
  lead's owner. Before, only a saved result counted: a lead called twice and sent a
  WhatsApp moved as "No call in 30 work minutes". Those actions now also set
  ``first_contact_at`` (store.py), and this check reads the history too, so a lead worked
  before that change is not moved either.
- **A cap.** At most ``HOPS_PER_DAY`` automatic moves per lead per day (India's day);
  then it waits for a manager ("Needs a manager", no owner, a bell line for the owners,
  admins and managers) instead of going round again. Two old Meta leads moved five times
  each, every 30 minutes, and nobody called them. A move never hands a lead back to
  someone it left today.
- **Not retroactive.** Only leads given out after the rule was switched on
  (``ENABLED_AT`` in the settings) move. A workspace switched on before this field
  existed gets it at its first sweep, so what was given out before stays put.
- **Not to someone away.** A seller not seen in the app for ``away_after_hours`` work
  hours (default ``AWAY_HOURS``), or who said they are not taking leads, is skipped as the
  next owner; with nobody left, the lead waits for a manager. (Wise Life: 40 % of the
  split went to a seller whose app had been closed since 14:59.)
- A lead a seller added or took for themselves is theirs: it never moves by itself.

Each move adds one audit event (ids and counts only) besides its history line, and the
sweep keeps counts for the API's log line (``reassign.py``).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import and_, exists, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from ac_platform.identity.models import Session as IdentitySession
from ac_platform.lead_desk import hours as work_hours
from ac_platform.lead_desk.models import Lead, LeadEvent

# When the workspace switched auto-reassign on (ISO time, in the Lead Desk settings).
ENABLED_AT: Final = "auto_reassign_since"
# Work hours without the app before a seller counts as away (settings key, default).
AWAY_KEY: Final = "away_after_hours"
AWAY_HOURS: Final = 2.0
# Automatic moves per lead per day before it waits for a manager.
HOPS_PER_DAY: Final = 2
# A call the phone logged counts as contact from this long.
CALL_SECONDS: Final = 10
# The history line's mark on an automatic move (``data["auto"]``).
NO_CALL: Final = "no_call"
# The words a lead waiting for a manager starts with (its owner_reason).
NEEDS_MANAGER: Final = "Needs a manager:"
# Before the mark existed, an automatic move said this.
OLD_WORDS: Final = "No call in "
AUDIT_RESOURCE: Final = "lead_desk.lead"
AUDIT_MOVED: Final = "lead_desk.lead.auto_reassigned"
AUDIT_WAITING: Final = "lead_desk.lead.auto_reassign_needs_manager"


def enabled_at(config: Mapping[str, Any]) -> datetime | None:
    """When auto-reassign was switched on, if the settings say."""
    value = config.get(ENABLED_AT)
    if not isinstance(value, str):
        return None
    try:
        found = datetime.fromisoformat(value)
    except ValueError:
        return None
    return found if found.tzinfo is not None else None


def away_hours(config: Mapping[str, Any]) -> float:
    value = config.get(AWAY_KEY)
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return float(value)
    return AWAY_HOURS


def not_contacted() -> ColumnElement[bool]:
    """A lead nobody has reached for: no result, no first contact, and no call, message
    or owner's note in its history (see the module's note)."""
    event = aliased(LeadEvent)
    data = event.data
    call = and_(
        event.kind == "call",
        or_(
            func.coalesce(data["via"].as_string(), "") != "phone",
            func.coalesce(data["duration_seconds"].as_float(), 0) >= CALL_SECONDS,
        ),
    )
    message = and_(
        event.kind == "message",
        event.actor_person_id.is_not(None),
        func.coalesce(data["failed"].as_boolean(), false()).is_(false()),
    )
    note = and_(event.kind == "note", event.actor_person_id == Lead.owner_person_id)
    return and_(
        Lead.attempts == 0,
        Lead.first_contact_at.is_(None),
        ~exists().where(
            event.tenant_id == Lead.tenant_id,
            event.lead_id == Lead.id,
            or_(event.kind == "result", call, message, note),
        ),
    )


@dataclass
class Moves:
    """One lead's hand-overs as the sweep needs them."""

    auto_today: int = 0
    # Everyone it left today (it never goes back to them today).
    left_today: set[UUID] = field(default_factory=set)
    # Its owner took it or added it for themselves (it never moves by itself).
    own_pick: bool = False


def _is_auto(kind: str, actor: UUID | None, data: Mapping[str, Any]) -> bool:
    if kind != "reassigned" or actor is not None:
        return False
    return data.get("auto") == NO_CALL or str(data.get("reason_text") or "").startswith(OLD_WORDS)


def _uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None


async def moves(
    db: AsyncSession, tenant_id: UUID, lead_ids: Iterable[UUID], day_start: datetime
) -> dict[UUID, Moves]:
    """Each lead's automatic moves today, who it left today, and whether its owner picked
    it for themselves (from its last hand-over)."""
    ids = list(lead_ids)
    found: dict[UUID, Moves] = {lead_id: Moves() for lead_id in ids}
    if not ids:
        return found
    rows = (
        await db.execute(
            select(LeadEvent.lead_id, LeadEvent.kind, LeadEvent.actor_person_id, LeadEvent.data)
            .where(
                LeadEvent.tenant_id == tenant_id,
                LeadEvent.lead_id.in_(ids),
                LeadEvent.kind.in_(("assigned", "reassigned")),
            )
            .order_by(LeadEvent.lead_id, LeadEvent.created_at)
        )
    ).all()
    today = (
        await db.execute(
            select(
                LeadEvent.lead_id, LeadEvent.kind, LeadEvent.actor_person_id, LeadEvent.data
            ).where(
                LeadEvent.tenant_id == tenant_id,
                LeadEvent.lead_id.in_(ids),
                LeadEvent.kind.in_(("assigned", "reassigned")),
                LeadEvent.created_at >= day_start,
            )
        )
    ).all()
    for lead_id, _kind, actor, data in rows:
        given = data if isinstance(data, dict) else {}
        # The last hand-over wins: someone adding it for themselves ("self"; an add for
        # oneself passes no actor) or giving it to themselves.
        found[lead_id].own_pick = given.get("rule") == "self" or (
            actor is not None and _uuid(given.get("to")) == actor
        )
    for lead_id, kind, actor, data in today:
        given = data if isinstance(data, dict) else {}
        entry = found[lead_id]
        entry.auto_today += _is_auto(kind, actor, given)
        left = _uuid(given.get("from"))
        if left is not None:
            entry.left_today.add(left)
    return found


async def away(
    db: AsyncSession,
    person_ids: Iterable[UUID],
    *,
    hours: work_hours.WorkHours | None,
    now: datetime,
    after_hours: float,
) -> set[UUID]:
    """The people not seen in the app (any sign-in session's last request) for
    ``after_hours`` work hours; someone never seen is away."""
    ids = list(set(person_ids))
    if not ids:
        return set()
    seen = func.max(func.coalesce(IdentitySession.last_seen_at, IdentitySession.created_at))
    last: dict[UUID, datetime | None] = {
        person: at
        for person, at in (
            await db.execute(
                select(IdentitySession.person_id, seen)
                .where(IdentitySession.person_id.in_(ids))
                .group_by(IdentitySession.person_id)
            )
        ).tuples()
    }
    limit = after_hours * 60
    gone: set[UUID] = set()
    for person in ids:
        at = last.get(person)
        if at is None or work_hours.working_minutes(hours, at, now) >= limit:
            gone.add(person)
    return gone


@dataclass
class Tally:
    """What one sweep did, for the log line and the tests."""

    counts: Counter[str] = field(default_factory=Counter)

    def add(self, what: str, amount: int = 1) -> None:
        self.counts[what] += amount

    def line(self) -> str:
        return " ".join(f"{key}={value}" for key, value in sorted(self.counts.items()))
