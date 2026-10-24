"""Meetings and demos booked with a lead (Lead OS, 24 Oct 2026; the sales team's spec,
sections 2.5, 6 and 8).

A lead has one scheduled meeting at most (a unique index on the open row): a postponed
meeting moves, it is never booked twice. The row is the meeting as it stands; each
change adds a ``meeting`` event to the lead's history (booked, moved, held, missed,
cancelled), so nothing is lost when it moves. The event keeps whether there was a link,
never the link itself (links can carry a meeting's passcode).

- Booking a meeting sets the lead's next action to its start, and the lead moves to its
  pipeline's "meeting booked" stage when the move asks for a meeting.
- "It happened" moves the lead to the pipeline's "meeting held" stage, with the next
  follow-up while the deal is under consideration.
- Missed or cancelled asks where the lead stands now (spec: Not Connected, Interested
  or Discussion Incomplete).

The lead's seller gets a phone reminder before it starts (``push.py``), once per start
time: a moved meeting reminds again.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.lead_desk.contracts import MeetingInput, MeetingView
from ac_platform.lead_desk.journey.model import Journey, Stage
from ac_platform.lead_desk.models import Lead, LeadMeeting

if TYPE_CHECKING:
    from ac_platform.lead_desk.store import LeadDesk

MODES: Final[tuple[str, ...]] = ("zoom", "google_meet", "phone", "in_person", "other")
MODE_LABELS: Final[dict[str, str]] = {
    "zoom": "Zoom",
    "google_meet": "Google Meet",
    "phone": "Phone call",
    "in_person": "In person",
    "other": "Other",
}
# The seller's reminder (owner default, 24 Oct 2026: on, 30 minutes before).
REMIND_BEFORE: Final[timedelta] = timedelta(minutes=30)
# A meeting is booked from a little in the past (it is starting now) to a year ahead.
EARLIEST: Final[timedelta] = timedelta(hours=1)
LATEST: Final[timedelta] = timedelta(days=366)


class MeetingError(ValueError):
    """A meeting the seller must fix; the message is shown as is."""


def booked_stage(journey: Journey) -> Stage | None:
    """The pipeline's stage for a booked meeting, if it has one."""
    return next((s for s in journey.live if s.milestone == "appointment_booked"), None)


def held_stage(journey: Journey) -> Stage | None:
    """The pipeline's stage for a meeting that happened, if it has one."""
    return next((s for s in journey.live if s.milestone == "appointment_done"), None)


def clean_link(link: str | None) -> str | None:
    if link is None or not link.strip():
        return None
    value = link.strip()
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.netloc or " " in value:
        raise MeetingError("Paste the meeting link as it starts: https://")
    return value


def checked(meeting: MeetingInput, now: datetime) -> dict[str, Any]:
    """The meeting's fields, checked: a start in the next year, an https link."""
    starts = meeting.starts_at
    if starts < now - EARLIEST or starts > now + LATEST:
        raise MeetingError("Pick a meeting time in the next year.")
    return {
        "starts_at": starts,
        "duration_minutes": meeting.duration_minutes,
        "mode": meeting.mode,
        "link": clean_link(meeting.link),
        "location": (meeting.location or "").strip() or None,
        "agenda": (meeting.agenda or "").strip() or None,
    }


async def open_meeting(
    db: AsyncSession, tenant_id: UUID, lead_id: UUID, *, lock: bool = False
) -> LeadMeeting | None:
    query = select(LeadMeeting).where(
        LeadMeeting.tenant_id == tenant_id,
        LeadMeeting.lead_id == lead_id,
        LeadMeeting.status == "scheduled",
    )
    if lock:
        query = query.with_for_update()
    row: LeadMeeting | None = await db.scalar(query)
    return row


def view(row: LeadMeeting, host_name: str | None = None) -> MeetingView:
    return MeetingView(
        meeting_id=row.id,
        revision=row.revision,
        status=row.status,
        starts_at=row.starts_at,
        duration_minutes=row.duration_minutes,
        mode=row.mode,
        mode_label=MODE_LABELS.get(row.mode, "Other"),
        link=row.link,
        location=row.location,
        agenda=row.agenda,
        outcome_note=row.outcome_note,
        host_person_id=row.host_person_id,
        host_name=host_name,
    )


def _iso(at: datetime | None) -> str | None:
    return at.isoformat() if at else None


def book(
    desk: LeadDesk,
    lead: Lead,
    fields: dict[str, Any],
    *,
    command_id: UUID | None,
) -> LeadMeeting:
    """A new scheduled meeting for the lead, its history line, and the lead's next action."""
    row = LeadMeeting(
        id=uuid4(),
        tenant_id=desk.tenant_id,
        lead_id=lead.id,
        revision=1,
        status="scheduled",
        host_person_id=lead.owner_person_id,
        created_by_person_id=desk.viewer.person_id,
        created_at=desk.now,
        updated_at=desk.now,
        **fields,
    )
    desk.db.add(row)
    desk._event(
        lead,
        "meeting",
        {
            "meeting_id": str(row.id),
            "action": "scheduled",
            "starts_at": _iso(row.starts_at),
            "mode": row.mode,
            "location": row.location,
            "has_link": row.link is not None,
            "note": row.agenda,
        },
        actor=desk.viewer.person_id,
        command_id=command_id,
    )
    lead.next_action_at = row.starts_at
    lead.next_action_note = f"{MODE_LABELS.get(row.mode, 'Meeting')} meeting"
    return row


def move(
    desk: LeadDesk,
    lead: Lead,
    row: LeadMeeting,
    fields: dict[str, Any],
    *,
    command_id: UUID | None,
) -> None:
    """The same meeting at a new time or place; the history keeps where it was."""
    before_start, before_mode = row.starts_at, row.mode
    for name, value in fields.items():
        setattr(row, name, value)
    row.revision += 1
    row.updated_at = desk.now
    desk._event(
        lead,
        "meeting",
        {
            "meeting_id": str(row.id),
            "action": "rescheduled",
            "starts_at": _iso(row.starts_at),
            "from_starts_at": _iso(before_start),
            "mode": row.mode,
            "from_mode": before_mode,
            "location": row.location,
            "has_link": row.link is not None,
            "note": row.agenda,
        },
        actor=desk.viewer.person_id,
        command_id=command_id,
    )
    lead.next_action_at = row.starts_at


def close(
    desk: LeadDesk,
    lead: Lead,
    row: LeadMeeting,
    status: str,
    *,
    note: str | None,
    command_id: UUID | None = None,
) -> None:
    """The meeting is over: it happened (done), they didn't come (missed) or it was called
    off (cancelled)."""
    row.status = status
    row.closed_at = desk.now
    row.outcome_note = (note or "").strip()[:1000] or row.outcome_note
    row.revision += 1
    row.updated_at = desk.now
    desk._event(
        lead,
        "meeting",
        {
            "meeting_id": str(row.id),
            "action": status,
            "starts_at": _iso(row.starts_at),
            "mode": row.mode,
            "note": (note or "").strip()[:1000] or None,
        },
        actor=desk.viewer.person_id,
        command_id=command_id,
    )
