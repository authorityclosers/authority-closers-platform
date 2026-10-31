"""The seller's work views and the stage filter on the Leads list (Dipak's Home + Leads
handoff, 31 Oct 2026, items 56-73). Work views are not stages: To Call is the side's
customers needing a call today, next lead first; Follow-ups is the leads with planned or
overdue contact (Open Leads and Interested with a follow-up time), split into Due Today,
Overdue and Upcoming. The stage filter takes the owner's own stage (a step key); a lead
with no step, or one its list no longer has, counts in its kind's stage, so nothing falls
out of the list. Reads only."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import and_, case, false, func, or_

from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.models import Lead
from ac_platform.lead_desk.vocabulary import NEEDS_FOLLOW_UP, OPEN_STAGES

WorkView = Literal["to_call", "follow_ups"]
FollowUpWhen = Literal["today", "overdue", "upcoming"]


def in_view(view: WorkView, day_end: datetime) -> Any:
    """SQL for one work view."""
    if view == "to_call":
        # Due before today ends (late, retries, today's follow-ups), or new and never called.
        return and_(
            Lead.stage.in_(OPEN_STAGES),
            or_(
                Lead.next_action_at < day_end,
                and_(Lead.stage == "new", Lead.next_action_at.is_(None)),
            ),
        )
    # Planned contact: Open Leads and Interested with a time (retries stay in To Call).
    return and_(Lead.stage.in_(NEEDS_FOLLOW_UP), Lead.next_action_at.is_not(None))


def call_order(now: datetime, day_start: datetime) -> tuple[Any, ...]:
    """To Call's order, next lead first (Dipak's handoff p.12: a promised follow-up stays in
    sight when a new enquiry arrives, and an older backlog doesn't push fresh enquiries
    down): due today and already due, then new leads never called (oldest first), then the
    older backlog, then the rest of today; the lead's id last, so a page never repeats one.
    Home's next lead is the first row of this order (phone personas, 1 Nov 2026: Home said
    Kiara while Leads dialled Krishna)."""
    bucket = case(
        (and_(Lead.next_action_at >= day_start, Lead.next_action_at <= now), 0),
        (and_(Lead.stage == "new", Lead.next_action_at.is_(None)), 1),
        (Lead.next_action_at < day_start, 2),
        else_=3,
    )
    return (
        bucket,
        func.coalesce(Lead.next_action_at, Lead.created_at),
        Lead.created_at,
        Lead.id,
    )


def in_when(when: FollowUpWhen, day_start: datetime) -> Any:
    """SQL for Due Today (planned today), Overdue (planned before today) or Upcoming."""
    day_end = day_start + timedelta(days=1)
    if when == "overdue":
        return Lead.next_action_at < day_start
    if when == "upcoming":
        return Lead.next_action_at >= day_end
    return and_(Lead.next_action_at >= day_start, Lead.next_action_at < day_end)


def in_step(journey: journeys.Journey, key: str) -> Any:
    """SQL for the leads in one of the owner's stages."""
    stage = journey.by_key.get(key)
    if stage is None:
        return false()
    own = Lead.step == key
    fallback = journey.resolve(stage.kind, None)
    if fallback is None or fallback.key != key:
        return own
    # This stage takes its kind's leads that have no step of this list.
    return or_(
        own,
        and_(
            Lead.stage == stage.kind,
            or_(Lead.step.is_(None), Lead.step.not_in(list(journey.by_key))),
        ),
    )


def count_steps(journey: journeys.Journey, rows: Iterable[Any]) -> dict[str, int]:
    """Leads per owner's stage from (kind, step, count) rows, filed as in_step files them:
    by their own step, else in their kind's stage."""
    counts: dict[str, int] = {}
    for kind, own, count in rows:
        stage = journey.by_key.get(own) if own else None
        if stage is None:
            stage = journey.resolve(kind, None)
        if stage is not None:
            counts[stage.key] = counts.get(stage.key, 0) + int(count)
    return counts
