"""Sounds, one pick per moment (owner's round-2 board 4, option B, 20 Nov 2026): the sound
library's six Sales X-Ray moments, each with the team's sound and each person's own.

- The owner or an admin (``leads.manage``) sets the team's sound for each moment and
  whether sellers may pick their own (on by default).
- Anyone picks their own; with "sellers pick their own" off only the team's sound counts.
- A choice is a library sound id (``glass-v2.mention``), ``none`` or ``system`` (the phone's
  own sound), never a file or an address (brand kit, sound/SOUND-PICKER.md). A sound must be
  of its moment's kind: a ringtone rings an incoming call, a mention a lead given to you.
- What plays: the person's own, else the team's, else the library's default.

Kept in the organisation's Lead Desk settings under ``sounds`` (``team``, ``sellers_pick``
and ``people`` by person id), merged with the row locked, as ``notify`` is (notify_prefs.py).
No migration: the settings row is JSON already. The phone apps read :func:`resolve` through
the page's read, and a push may name the sound (``sound`` in its data).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Final, Literal, get_args
from uuid import UUID

from ac_platform.lead_desk.contracts import Command, Model
from ac_platform.lead_desk.models import LeadDeskSettings

if TYPE_CHECKING:
    from ac_platform.lead_desk.store import LeadDesk

KEY: Final = "sounds"

EventId = Literal[
    "sx.incoming_call",
    "sx.new_lead",
    "sx.new_message",
    "sx.follow_up_due",
    "sx.report_ready",
    "sx.upload_failed",
]
EVENTS: Final[tuple[EventId, ...]] = get_args(EventId)
# Each moment's kind and the library's default for it (library.json events[]; a test reads
# the web app's copy, public/sounds/library.json, so the two never drift).
KIND: Final[Mapping[str, str]] = {
    "sx.incoming_call": "ringtone",
    "sx.new_lead": "mention",
    "sx.new_message": "message",
    "sx.follow_up_due": "reminder",
    "sx.report_ready": "success",
    "sx.upload_failed": "error",
}
DEFAULT: Final[Mapping[str, str]] = {
    "sx.incoming_call": "glass-v3.ringtone",
    "sx.new_lead": "glass-v2.mention",
    "sx.new_message": "glass-v2.message",
    "sx.follow_up_due": "glass-v2.reminder",
    "sx.report_ready": "glass-v1.success",
    "sx.upload_failed": "glass-v3.error",
}
PACKS: Final = (
    "A",
    "B",
    "C",
    "glass-v1",
    "glass-v2",
    "glass-v3",
    "warm-v1",
    "warm-v2",
    "warm-v3",
    "pulse-v1",
    "pulse-v2",
    "pulse-v3",
)
KINDS: Final = ("ringtone", "message", "mention", "reminder", "success", "error")
# Not a sound: silence, or whatever the phone itself plays.
NONE: Final = "none"
SYSTEM: Final = "system"
_ID = re.compile(r"^([A-Za-z0-9-]{1,16})\.([a-z]{1,16})$")


def valid(event: str, choice: Any) -> bool:
    """Whether this choice may play for this moment: none, the phone's own, or a library
    sound of the moment's kind."""
    if event not in KIND or not isinstance(choice, str):
        return False
    if choice in (NONE, SYSTEM):
        return True
    match = _ID.match(choice)
    return match is not None and match[1] in PACKS and match[2] == KIND[event]


def _picks(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {event: value[event] for event in EVENTS if valid(event, value.get(event))}


def _stored(config: Mapping[str, Any]) -> Mapping[str, Any]:
    stored = config.get(KEY)
    return stored if isinstance(stored, Mapping) else {}


def team(config: Mapping[str, Any]) -> dict[str, str]:
    """The team's sound for each moment: its pick, else the library default."""
    picked = _picks(_stored(config).get("team"))
    return {event: picked.get(event, DEFAULT[event]) for event in EVENTS}


def sellers_pick(config: Mapping[str, Any]) -> bool:
    value = _stored(config).get("sellers_pick")
    return value if isinstance(value, bool) else True


def mine(config: Mapping[str, Any], person_id: UUID) -> dict[str, str]:
    """This person's own picks (only the moments they changed)."""
    people = _stored(config).get("people")
    if not isinstance(people, Mapping):
        return {}
    return _picks(people.get(str(person_id)))


def resolve(config: Mapping[str, Any], person_id: UUID, event: EventId) -> str:
    """What plays for this person: their own (while sellers may pick), else the team's."""
    own = mine(config, person_id) if sellers_pick(config) else {}
    return own.get(event) or team(config)[event]


def own_picks(config: Mapping[str, Any]) -> int:
    """How many people picked a sound of their own (the owner's page says so)."""
    people = _stored(config).get("people")
    if not isinstance(people, Mapping):
        return 0
    return sum(1 for picks in people.values() if _picks(picks))


# ----- the page -------------------------------------------------------------------------------


class SoundRow(Model):
    id: str
    team: str
    # This person's own pick, or None for the team's.
    mine: str | None
    # What plays for this person now.
    plays: str


class SoundsView(Model):
    events: list[SoundRow]
    sellers_pick: bool
    # Owners, admins and managers set the team's sounds.
    manager: bool
    # How many people picked their own.
    own_picks: int


class MySoundsCommand(Command):
    # A moment's own pick, or None to go back to the team's. Moments left out are kept.
    mine: dict[str, str | None]


class TeamSoundsCommand(Command):
    team: dict[str, str]
    sellers_pick: bool


def view_of(config: Mapping[str, Any], person_id: UUID, manager: bool) -> SoundsView:
    picks = team(config)
    own = mine(config, person_id)
    return SoundsView(
        events=[
            SoundRow(
                id=event,
                team=picks[event],
                mine=own.get(event),
                plays=resolve(config, person_id, event),
            )
            for event in EVENTS
        ],
        sellers_pick=sellers_pick(config),
        manager=manager,
        own_picks=own_picks(config),
    )


async def view(desk: LeadDesk) -> SoundsView:
    _, config = await desk.settings()
    return view_of(config, desk.viewer.person_id, desk.viewer.can_manage)


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


def _bad(event: str, choice: Any) -> bool:
    return event not in KIND or (choice is not None and not valid(event, choice))


async def save_mine(desk: LeadDesk, command: MySoundsCommand) -> SoundsView:
    """A person's own picks; refused while the team's sounds are the only ones."""
    from ac_platform.lead_desk.errors import DeskError

    if any(_bad(event, choice) for event, choice in command.mine.items()):
        raise DeskError(422, "Pick one of the library's sounds for that moment.")
    row = await _row(desk)
    config = row.config or {}
    if not sellers_pick(config) and not desk.viewer.can_manage:
        raise DeskError(403, "Your team uses the same sounds for everyone.")
    stored = dict(_stored(config))
    people = dict(stored.get("people") or {}) if isinstance(stored.get("people"), Mapping) else {}
    merged = _picks(people.get(str(desk.viewer.person_id)))
    for event, choice in command.mine.items():
        if choice is None:
            merged.pop(event, None)
        else:
            merged[event] = choice
    if merged:
        people[str(desk.viewer.person_id)] = merged
    else:
        people.pop(str(desk.viewer.person_id), None)
    row.config = {**config, KEY: {**stored, "people": people}}
    await desk.db.flush()
    return view_of(row.config, desk.viewer.person_id, desk.viewer.can_manage)


async def save_team(desk: LeadDesk, command: TeamSoundsCommand) -> SoundsView:
    """The team's sounds (owners, admins and managers; the route asks for a manager)."""
    from ac_platform.lead_desk.errors import DeskError

    if any(event not in KIND or not valid(event, choice) for event, choice in command.team.items()):
        raise DeskError(422, "Pick one of the library's sounds for that moment.")
    row = await _row(desk)
    config = row.config or {}
    stored = dict(_stored(config))
    picked = {**_picks(stored.get("team")), **command.team}
    # The library's default is kept as no pick, so a new default reaches the team.
    stored["team"] = {
        event: choice for event, choice in picked.items() if DEFAULT.get(event) != choice
    }
    stored["sellers_pick"] = command.sellers_pick
    row.config = {**config, KEY: stored}
    await desk.db.flush()
    return view_of(row.config, desk.viewer.person_id, desk.viewer.can_manage)


__all__ = [
    "DEFAULT",
    "EVENTS",
    "KIND",
    "EventId",
    "MySoundsCommand",
    "SoundsView",
    "TeamSoundsCommand",
    "resolve",
    "save_mine",
    "save_team",
    "sellers_pick",
    "team",
    "valid",
    "view",
    "view_of",
]
