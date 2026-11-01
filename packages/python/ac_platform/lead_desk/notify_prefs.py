"""Each person's own notification choices (competitor teardown 26, 1 Nov 2026): one page
that says what reaches their phone and when.

- New enquiry: a lead given to them, at once.
- Follow-up due: at the time they planned, or 15 minutes or an hour before.
- Missed follow-up: the sweep of what is late (12, 2, 4 and 6 o'clock).
- Team alerts: owners' and admins' alerts (``owner_alerts``).
- Quiet outside working hours: nothing buzzes outside the team's working hours, except a
  follow-up the person set for that time themselves. Without working hours every hour counts.

Every type is on and on time, and quiet hours off, by default, so a person who never opens
the page hears what they heard before (the Leads session's condition, 1 Nov 2026). Kept
per person in the organisation's Lead Desk settings under ``notify``, merged with the row
locked and the revision unchanged, as each phone's setup is.
The senders ask :func:`allows` and :func:`due_lead`; a test push goes to the person's own
phones, and its words are read on their own session like every alert's.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, Literal, get_args
from uuid import UUID

from sqlalchemy import func, select

from ac_platform.lead_desk import hours as work_hours
from ac_platform.lead_desk.contracts import AlertText, Command, Model
from ac_platform.lead_desk.models import LeadDeskSettings, LeadDevice

if TYPE_CHECKING:
    from ac_platform.lead_desk.store import LeadDesk

KEY: Final = "notify"
Kind = Literal["new_enquiry", "follow_up_due", "missed_follow_up", "team_alerts"]
KINDS: Final[tuple[Kind, ...]] = get_args(Kind)
# A follow-up's alert: at the time, 15 minutes before, or an hour before.
DUE_LEADS: Final[tuple[int, ...]] = (0, 15, 60)
# How far ahead the alerts' pass looks for follow-ups someone hears early.
MAX_DUE_LEAD: Final = timedelta(minutes=max(DUE_LEADS))
# A test's words answer the app's read for this long.
TEST_WORDS_FOR: Final = timedelta(minutes=3)
TEST_EVERY: Final = timedelta(minutes=1)


@dataclass(frozen=True, slots=True)
class Prefs:
    on: Mapping[Kind, bool]
    due_lead_minutes: int
    quiet: bool
    test_at: datetime | None


def _when(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def read(config: Mapping[str, Any], person_id: UUID) -> Prefs:
    everyone = config.get(KEY)
    mine: Mapping[str, Any] = {}
    if isinstance(everyone, Mapping) and isinstance(everyone.get(str(person_id)), Mapping):
        mine = everyone[str(person_id)]
    lead = mine.get("due_lead_minutes")
    return Prefs(
        on={kind: mine[kind] if isinstance(mine.get(kind), bool) else True for kind in KINDS},
        due_lead_minutes=lead if lead in DUE_LEADS else 0,
        quiet=mine["quiet"] if isinstance(mine.get("quiet"), bool) else False,
        test_at=_when(mine.get("test_at")),
    )


def allows(config: Mapping[str, Any], person_id: UUID, kind: Kind, now: datetime) -> bool:
    """Whether this person hears this kind now: switched on, and, with quiet on, inside the
    team's working hours (a follow-up they set for a time is theirs to hear)."""
    prefs = read(config, person_id)
    if not prefs.on[kind]:
        return False
    if prefs.quiet and kind != "follow_up_due":
        return work_hours.inside(work_hours.parse(config), now)
    return True


def due_lead(config: Mapping[str, Any], person_id: UUID) -> timedelta:
    """How long before a follow-up this person hears of it (0 is at the time)."""
    return timedelta(minutes=read(config, person_id).due_lead_minutes)


def _write(row: LeadDeskSettings, person_id: UUID, **changes: Any) -> None:
    everyone = dict(row.config.get(KEY) or {}) if isinstance(row.config.get(KEY), Mapping) else {}
    mine = everyone.get(str(person_id))
    merged = dict(mine) if isinstance(mine, Mapping) else {}
    merged.update(changes)
    everyone[str(person_id)] = merged
    row.config = {**row.config, KEY: everyone}


# ----- the page -------------------------------------------------------------------------------


class NotifyView(Model):
    new_enquiry: bool
    follow_up_due: bool
    missed_follow_up: bool
    team_alerts: bool
    due_lead_minutes: int
    quiet: bool
    # The team's working hours in words ("10:30–7:00, Mon–Sat"), or None when none are set.
    working_hours: str | None
    # Owners and admins also choose team alerts and the day's summary.
    manager: bool
    phones: int


class NotifyCommand(Command):
    new_enquiry: bool
    follow_up_due: bool
    missed_follow_up: bool
    team_alerts: bool
    due_lead_minutes: int
    quiet: bool


_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _clock(value: Any) -> str:
    text = value.strftime("%H:%M")
    hours, minutes = (int(part) for part in text.split(":"))
    return f"{hours % 12 or 12}:{minutes:02d}"


def hours_words(config: Mapping[str, Any]) -> str | None:
    hours = work_hours.parse(config)
    if hours is None:
        return None
    days = list(hours.days)
    run = days == list(range(days[0], days[-1] + 1))
    named = (
        f"{_DAYS[days[0]]}–{_DAYS[days[-1]]}"
        if run and len(days) > 2
        else ", ".join(_DAYS[day] for day in days)
    )
    return f"{_clock(hours.start)}–{_clock(hours.end)}, {named}"


async def view(desk: LeadDesk) -> NotifyView:
    _, config = await desk.settings()
    prefs = read(config, desk.viewer.person_id)
    phones = await desk.db.scalar(
        select(func.count()).where(
            LeadDevice.tenant_id == desk.tenant_id,
            LeadDevice.person_id == desk.viewer.person_id,
        )
    )
    return NotifyView(
        new_enquiry=prefs.on["new_enquiry"],
        follow_up_due=prefs.on["follow_up_due"],
        missed_follow_up=prefs.on["missed_follow_up"],
        team_alerts=prefs.on["team_alerts"],
        due_lead_minutes=prefs.due_lead_minutes,
        quiet=prefs.quiet,
        working_hours=hours_words(config),
        manager=desk.viewer.can_manage,
        phones=int(phones or 0),
    )


async def _row(desk: LeadDesk) -> LeadDeskSettings:
    row = await desk.db.get(LeadDeskSettings, desk.tenant_id, with_for_update=True)
    if row is None:
        row = LeadDeskSettings(
            tenant_id=desk.tenant_id,
            revision=1,
            config={},
            updated_by_person_id=desk.viewer.person_id,
            updated_at=desk.now,
        )
        desk.db.add(row)
    return row


async def save(desk: LeadDesk, command: NotifyCommand) -> NotifyView:
    """A person's own choices; anyone in the workspace sets their own."""
    from ac_platform.lead_desk.errors import DeskError

    if command.due_lead_minutes not in DUE_LEADS:
        raise DeskError(422, "Pick at the time, 15 minutes before or an hour before.")
    row = await _row(desk)
    _write(
        row,
        desk.viewer.person_id,
        new_enquiry=command.new_enquiry,
        follow_up_due=command.follow_up_due,
        missed_follow_up=command.missed_follow_up,
        team_alerts=command.team_alerts,
        due_lead_minutes=command.due_lead_minutes,
        quiet=command.quiet,
    )
    await desk.db.flush()
    return await view(desk)


@dataclass(slots=True)
class TestPush:
    tenant_id: UUID
    person_id: UUID
    tokens: list[str]

    def data(self) -> dict[str, str]:
        """No lead and no words: the app reads them on the person's own session."""
        return {"type": "lead_desk", "kind": "test", "tenant": str(self.tenant_id)}


async def test(desk: LeadDesk) -> TestPush:
    """A test to this person's own phones (the caller commits, then sends). Once a minute."""
    from ac_platform.lead_desk.errors import DeskError

    row = await _row(desk)
    prefs = read(row.config or {}, desk.viewer.person_id)
    if prefs.test_at is not None and desk.now - prefs.test_at < TEST_EVERY:
        raise DeskError(429, "A test just went. Try again in a minute.")
    tokens = list(
        (
            await desk.db.scalars(
                select(LeadDevice.token).where(
                    LeadDevice.tenant_id == desk.tenant_id,
                    LeadDevice.person_id == desk.viewer.person_id,
                )
            )
        ).all()
    )
    _write(row, desk.viewer.person_id, test_at=desk.now.isoformat())
    await desk.db.flush()
    return TestPush(desk.tenant_id, desk.viewer.person_id, tokens)


async def test_words(desk: LeadDesk) -> AlertText | None:
    """The words of a test this person just sent, for the app's plain alert read."""
    _, config = await desk.settings()
    at = read(config, desk.viewer.person_id).test_at
    if at is None or not timedelta(0) <= desk.now - at <= TEST_WORDS_FOR:
        return None
    return AlertText(
        title="Test notification",
        body="Alerts reach this phone. Tap to open Sales X-Ray.",
        lead_id=None,
        url="/leads",
    )
