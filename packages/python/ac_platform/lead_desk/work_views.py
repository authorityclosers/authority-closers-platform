"""The seller's work views and the stage filter on the Leads list (Dipak's Home + Leads
handoff, 31 Oct 2026, items 56-73). Work views are not stages: To Call is the side's
customers needing a call today, next lead first; Follow-ups is the leads with planned or
overdue contact (any open lead with a time: a follow-up, a retry, a booked call-back), split
into Due Today, Overdue and Upcoming. The stage filter takes the owner's own stage (a step
key); a lead with no step, or one its list no longer has, counts in its kind's stage, so
nothing falls out of the list. Reads only."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from datetime import datetime, timedelta
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import and_, case, false, func, or_

from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.models import Lead
from ac_platform.lead_desk.vocabulary import OPEN_STAGES

WorkView = Literal["to_call", "follow_ups"]
FollowUpWhen = Literal["today", "overdue", "upcoming"]
# A new Inbound enquiry this recent and never called is the top of To Call (teardown #4).
FRESH_ENQUIRY: Final = timedelta(hours=24)


def in_view(view: WorkView, day_end: datetime, waiting: Collection[UUID] = ()) -> Any:
    """SQL for one work view. ``waiting``: the leads who called and weren't reached since
    (LeadDesk._waiting_call_back), which To Call holds too."""
    if view == "to_call":
        # Due before today ends (late, retries, today's follow-ups), or new and never called,
        # or a missed call not yet called back (orchestrator, 1 Nov 2026, #9 option A: the
        # badge counts exactly these rows, so a missed call is a row, not a number alone).
        return and_(
            Lead.stage.in_(OPEN_STAGES),
            or_(
                Lead.next_action_at < day_end,
                and_(Lead.stage == "new", Lead.next_action_at.is_(None)),
                Lead.id.in_(list(waiting)) if waiting else false(),
            ),
        )
    # Planned contact: any open lead with a time, on its side (phone personas, 1 Nov 2026:
    # ph2-14, a "No answer" retry showed nowhere but All Leads; ph2-18, a Cold lead's booked
    # call-back never reached Cold > Follow-ups). A retry due today is in To Call too.
    return and_(Lead.stage.in_(OPEN_STAGES), Lead.next_action_at.is_not(None))


def call_order(now: datetime, day_start: datetime) -> tuple[Any, ...]:
    """To Call's order, next lead first. A new Inbound enquiry nobody has called, received
    in the last 24 hours, is the top, newest first (competitor teardown #4, speed to lead:
    it jumps to the top of To Call and is the next card in a round). Then, as Dipak's
    handoff p.12 has it (a promised follow-up stays in sight when a new enquiry arrives,
    and an older backlog doesn't push fresh enquiries down): due today and already due,
    then new leads never called (oldest first), then the older backlog, then the rest of
    today; the lead's id last, so a page never repeats one. A missed call not yet returned
    goes ahead of all of it (call_backs_first).
    Home's next lead is the first row of this order (phone personas, 1 Nov 2026: Home said
    Kiara while Leads dialled Krishna)."""
    arrived = func.coalesce(Lead.received_at, Lead.created_at)
    fresh = and_(
        Lead.stage == "new",
        Lead.next_action_at.is_(None),
        func.coalesce(Lead.pipeline, "live") != "cold",
        arrived >= now - FRESH_ENQUIRY,
    )
    bucket = case(
        (fresh, 0),
        (and_(Lead.next_action_at >= day_start, Lead.next_action_at <= now), 1),
        (and_(Lead.stage == "new", Lead.next_action_at.is_(None)), 2),
        (Lead.next_action_at < day_start, 3),
        else_=4,
    )
    return (
        bucket,
        # The newest fresh enquiry first; the other buckets keep their order below.
        case((fresh, arrived), else_=None).desc().nulls_last(),
        func.coalesce(Lead.next_action_at, Lead.created_at),
        Lead.created_at,
        Lead.id,
    )


def call_backs_first(waiting: Collection[UUID]) -> tuple[Any, ...]:
    """Ahead of call_order: the leads waiting for a call back, who rang while nobody
    picked up (#9 option A). Nothing when none wait."""
    return (case((Lead.id.in_(list(waiting)), 0), else_=1),) if waiting else ()


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
