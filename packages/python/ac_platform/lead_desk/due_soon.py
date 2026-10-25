"""What is due within the hour, for the red banner in the app (owner, 25 Oct 2026, the client
demo: "in the app, a red top banner such as <lead> follow-up in 1 hour, with a haptic").

The soonest of this person's own: a lead's next call, an open task, a booked meeting they
host, due from five minutes ago to an hour from now; nothing outside the workspace's work hours
(the app's quiet time; every hour counts when none are set). Read on the person's own
session, so it may name the lead; a push never does.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final
from uuid import UUID

from sqlalchemy import and_, select

from ac_platform.lead_desk import hours as work_hours
from ac_platform.lead_desk.contracts import Soon, SoonItem
from ac_platform.lead_desk.models import Lead, LeadMeeting, LeadTask
from ac_platform.lead_desk.vocabulary import OPEN_STAGES

if TYPE_CHECKING:
    from ac_platform.lead_desk.store import LeadDesk

AHEAD: Final = timedelta(hours=1)
BEHIND: Final = timedelta(minutes=5)
WHAT: Final = {"follow_up": "follow-up", "task": "task", "meeting": "meeting"}


def words(name: str, what: str, minutes: int) -> str:
    when = "now" if minutes <= 0 else f"in {minutes} min" if minutes < 60 else "in 1 hour"
    return f"{name}: {WHAT[what]} {when}"


async def soon(desk: LeadDesk) -> Soon:
    _, config = await desk.settings()
    if not work_hours.inside(work_hours.parse(config), desk.now):
        return Soon(item=None, generated_at=desk.now)
    me = desk.viewer.person_id
    start, end = desk.now - BEHIND, desk.now + AHEAD
    found: list[tuple[datetime, str, UUID, str, str | None]] = []
    lead = (
        await desk.db.execute(
            select(Lead.next_action_at, Lead.id, Lead.name)
            .where(
                Lead.tenant_id == desk.tenant_id,
                Lead.owner_person_id == me,
                Lead.stage.in_(OPEN_STAGES),
                Lead.next_action_at >= start,
                Lead.next_action_at <= end,
            )
            .order_by(Lead.next_action_at, Lead.id)
            .limit(1)
        )
    ).first()
    if lead is not None:
        found.append((lead[0], "follow_up", lead[1], lead[2], None))
    task = (
        await desk.db.execute(
            select(LeadTask.starts_at, LeadTask.lead_id, Lead.name, LeadTask.title)
            .join(Lead, and_(Lead.id == LeadTask.lead_id, Lead.tenant_id == LeadTask.tenant_id))
            .where(
                LeadTask.tenant_id == desk.tenant_id,
                LeadTask.owner_person_id == me,
                LeadTask.status == "open",
                LeadTask.starts_at >= start,
                LeadTask.starts_at <= end,
            )
            .order_by(LeadTask.starts_at, LeadTask.id)
            .limit(1)
        )
    ).first()
    if task is not None:
        found.append((task[0], "task", task[1], task[2], task[3]))
    meeting = (
        await desk.db.execute(
            select(LeadMeeting.starts_at, LeadMeeting.lead_id, Lead.name)
            .join(
                Lead, and_(Lead.id == LeadMeeting.lead_id, Lead.tenant_id == LeadMeeting.tenant_id)
            )
            .where(
                LeadMeeting.tenant_id == desk.tenant_id,
                LeadMeeting.host_person_id == me,
                LeadMeeting.status == "scheduled",
                LeadMeeting.starts_at >= start,
                LeadMeeting.starts_at <= end,
            )
            .order_by(LeadMeeting.starts_at, LeadMeeting.id)
            .limit(1)
        )
    ).first()
    if meeting is not None:
        found.append((meeting[0], "meeting", meeting[1], meeting[2], None))
    if not found:
        return Soon(item=None, generated_at=desk.now)
    # The soonest; a meeting before a task before a follow-up at the same minute.
    rank = {"meeting": 0, "task": 1, "follow_up": 2}
    at, what, lead_id, name, title = min(found, key=lambda item: (item[0], rank[item[1]]))
    minutes = max(0, round((at - desk.now).total_seconds() / 60))
    return Soon(
        item=SoonItem(
            lead_id=lead_id,
            lead_name=name,
            what=what,
            at=at,
            minutes=minutes,
            title=title,
            words=words(name, what, minutes),
        ),
        generated_at=desk.now,
    )
