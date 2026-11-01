"""Revenue milestones on the phone (competitor teardown #27, 1 Nov 2026).

When a seller's won revenue reaches half of their month's target, and again when it reaches
all of it, the seller and the workspace's owners and admins hear it on their phones; when the
team's does, the owners and admins do. A seller's target is their own or an even share of the
organisation's, and the team's is the organisation's or the sellers' own added up, as Home's
bar counts them (``revenue``).

Each mark goes once a month for each seller and for the team. What was sent lives in the
workspace's Lead Desk settings under ``revenue_milestones``: the month, the highest mark sent
for each, when the last pass looked, and the last few minutes' pushes (ids and amounts only),
written the way owner alerts are (the row locked, merged, the revision unchanged). A pass that
finds both marks passed sends the higher one. The first pass that finds a target only notes
where each stands, so a deploy (or a target set) late in a month sends nothing old; a workspace
with no Lead Desk settings yet gets its settings row (revision 1) from that pass. A workspace
with no target this month costs one read and writes nothing. The push carries no name and no
amount; the app reads the words on the person's own session (``GET /v1/lead-desk/alert``).

It runs in the lead alerts' pass (``push.tick``), under that pass's lock.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.lead_desk import revenue as revenue_rules
from ac_platform.lead_desk import sla
from ac_platform.lead_desk.contracts import AlertText
from ac_platform.lead_desk.facets import rupees
from ac_platform.lead_desk.models import LeadDeskSettings, LeadDevice
from ac_platform.tenancy.models import Membership

if TYPE_CHECKING:
    from ac_platform.lead_desk.store import LeadDesk

KEY: Final = "revenue_milestones"
MARKS: Final = (50, 100)
TEAM: Final = "team"
# Each workspace is looked at once a minute, though the alerts' pass runs more often.
EVERY: Final = timedelta(minutes=1)
# The app reads the words as the push arrives; they answer this long.
WORDS_NOW: Final = timedelta(minutes=3)


@dataclass(slots=True)
class RevenueAlert:
    """One push to one person: the mark, never a name or an amount."""

    tenant_id: UUID
    person_id: UUID
    mark: int
    tokens: list[str] = field(default_factory=list)

    def data(self) -> dict[str, str]:
        return {
            "type": "lead_desk",
            "kind": "revenue",
            "tenant": str(self.tenant_id),
            "count": "1",
            "mark": str(self.mark),
        }


@dataclass(frozen=True, slots=True)
class State:
    month: str | None
    # The highest mark sent this month: "team" or a seller's id.
    sent: Mapping[str, int]
    checked_at: datetime | None
    recent: tuple[Mapping[str, Any], ...]


def _when(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def read(config: Mapping[str, Any]) -> State:
    raw = config.get(KEY)
    found: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    sent = found.get("sent")
    recent = found.get("recent")
    month = found.get("month")
    return State(
        month=month if isinstance(month, str) else None,
        sent={
            str(subject): mark
            for subject, mark in (sent.items() if isinstance(sent, Mapping) else ())
            if isinstance(mark, int)
        },
        checked_at=_when(found.get("checked_at")),
        recent=tuple(
            item for item in (recent if isinstance(recent, list) else ()) if isinstance(item, dict)
        ),
    )


def reached(won: int, target: int | None) -> int:
    """The highest mark the won revenue has reached, 0 for none."""
    if not target or target <= 0:
        return 0
    return max((mark for mark in MARKS if won * 100 >= target * mark), default=0)


def short(amount: int) -> str:
    """₹2.5 L, as Home's bar writes amounts (``inr`` in revenue-client.ts)."""
    for size, unit in ((10_000_000, "Cr"), (100_000, "L")):
        if amount >= size:
            value = Decimal(amount) / size
            step = Decimal(1) if value >= 100 else Decimal("0.1")
            return f"₹{value.quantize(step, rounding=ROUND_HALF_UP).normalize():f} {unit}"
    return rupees(amount)


async def standing(desk: LeadDesk, month: date) -> dict[str, tuple[int, int]]:
    """Won and target this month, for the team and each seller with a target."""
    organisation, own = await revenue_rules._targets(desk, month)
    if not organisation and not own:
        return {}
    start, end = revenue_rules.bounds(month)
    sellers = await revenue_rules._sellers(desk)
    share = revenue_rules.even_split(organisation, len(sellers))
    won_by: dict[UUID | None, int] = defaultdict(int)
    for row in (await revenue_rules._deals(desk, start, end)).values():
        won_by[row.credited_person_id] += row.amount
    found: dict[str, tuple[int, int]] = {}
    team_target = organisation or (sum(own.values()) or None)
    if team_target:
        found[TEAM] = (sum(won_by.values()), team_target)
    for person, _ in sellers:
        target = own.get(person, share)
        if target:
            found[str(person)] = (won_by.get(person, 0), target)
    return found


async def _phones(db: AsyncSession) -> dict[UUID, dict[UUID, tuple[str, list[str]]]]:
    """Everyone's phones, with their role, by workspace and person."""
    found: dict[UUID, dict[UUID, tuple[str, list[str]]]] = defaultdict(dict)
    for tenant_id, person_id, role, token in (
        await db.execute(
            select(LeadDevice.tenant_id, LeadDevice.person_id, Membership.role, LeadDevice.token)
            .join(
                Membership,
                and_(
                    Membership.tenant_id == LeadDevice.tenant_id,
                    Membership.person_id == LeadDevice.person_id,
                ),
            )
            .where(Membership.status == "active", Membership.ended_at.is_(None))
        )
    ).tuples():
        found[tenant_id].setdefault(person_id, (role, []))[1].append(token)
    return found


def _write(row: LeadDeskSettings, **changes: Any) -> None:
    """Merge into ``revenue_milestones``; the settings' revision stays (like owner alerts)."""
    current = dict(row.config.get(KEY) or {}) if isinstance(row.config.get(KEY), Mapping) else {}
    current.update(changes)
    row.config = {**row.config, KEY: current}


async def collect(db: AsyncSession, now: datetime) -> list[RevenueAlert]:
    """The milestone pushes to send now, written to each workspace's settings first (the
    caller commits)."""
    from ac_platform.lead_desk.store import LeadDesk, Viewer

    out: list[RevenueAlert] = []
    month = revenue_rules.month_of(now)
    for tenant_id, phones in (await _phones(db)).items():
        row = await db.get(LeadDeskSettings, tenant_id, with_for_update=True)
        state = read((row.config or {}) if row is not None else {})
        if state.checked_at is not None and now - state.checked_at < EVERY:
            continue
        desk = LeadDesk(
            db,
            Viewer(person_id=next(iter(phones)), tenant_id=tenant_id, role="member", name=""),
            now=now,
        )
        found = await standing(desk, month)
        if not found:
            # No target this month: nothing to reach, nothing written.
            continue
        if row is None:
            # A target set before any other setting: the workspace's settings start here.
            await db.execute(
                insert(LeadDeskSettings)
                .values(tenant_id=tenant_id, revision=1, config={}, updated_at=now)
                .on_conflict_do_nothing(index_elements=["tenant_id"])
            )
            row = await db.get(LeadDeskSettings, tenant_id, with_for_update=True)
            if row is None:
                continue
        first = state.checked_at is None
        sent = dict(state.sent) if state.month == month.isoformat() else {}
        recent = [
            entry
            for entry in state.recent
            if (at := _when(entry.get("at"))) is not None and now - at <= WORDS_NOW
        ]
        managers = [person for person, (role, _) in phones.items() if role in sla.MANAGERS]
        heard: dict[UUID, int] = {}
        for subject, (won, target) in found.items():
            mark = reached(won, target)
            if mark <= sent.get(subject, 0):
                continue
            sent[subject] = mark
            if first:
                continue
            people = list(managers)
            if subject != TEAM and UUID(subject) in phones and UUID(subject) not in people:
                people.append(UUID(subject))
            if not people:
                continue
            recent.append(
                {
                    "subject": subject,
                    "mark": mark,
                    "won": won,
                    "target": target,
                    "month": month.isoformat(),
                    "people": [str(person) for person in people],
                    "at": now.isoformat(),
                }
            )
            for person in people:
                heard[person] = max(heard.get(person, 0), mark)
        out.extend(
            RevenueAlert(tenant_id, person, mark, list(phones[person][1]))
            for person, mark in heard.items()
        )
        _write(row, month=month.isoformat(), sent=sent, checked_at=now.isoformat(), recent=recent)
    return out


def _month_name(month: str) -> str:
    return date.fromisoformat(month).strftime("%B")


async def _title(desk: LeadDesk, entry: Mapping[str, Any], me: str) -> str:
    subject, half = entry["subject"], entry["mark"] == 50
    name = _month_name(entry["month"])
    if subject == TEAM:
        return (
            f"The team is halfway to {name}'s target"
            if half
            else f"The team reached {name}'s target"
        )
    if subject == me:
        return f"Halfway to your {name} target" if half else f"{name} target reached"
    from ac_platform.identity.models import Person
    from ac_platform.lead_desk.store import person_name

    who = person_name(await desk.db.get(Person, UUID(subject)))
    return f"{who} is halfway to {name}'s target" if half else f"{who} reached {name}'s target"


def _whole(entry: Mapping[str, Any]) -> bool:
    return (
        isinstance(entry.get("subject"), str)
        and entry.get("mark") in MARKS
        and isinstance(entry.get("won"), int)
        and isinstance(entry.get("target"), int)
        and isinstance(entry.get("month"), str)
    )


async def words(desk: LeadDesk, *, now: datetime | None = None) -> AlertText | None:
    """The words of the milestones just sent to this person (one push a pass): their own
    first, then a seller's, the team's last. None when none of theirs is that fresh, so the
    usual words answer."""
    now = now or desk.now
    _, config = await desk.settings()
    me = str(desk.viewer.person_id)
    mine = [
        entry
        for entry in read(config).recent
        if _whole(entry)
        and me in entry.get("people", ())
        and (at := _when(entry.get("at"))) is not None
        and now - at <= WORDS_NOW
    ]
    if not mine:
        return None
    latest = max(str(entry.get("at")) for entry in mine)
    told = sorted(
        (entry for entry in mine if entry.get("at") == latest),
        key=lambda entry: (entry["subject"] != me, entry["subject"] == TEAM),
    )
    first, rest = told[0], told[1:]
    body = " · ".join(
        [
            f"{short(first['won'])} of {short(first['target'])} won",
            *[await _title(desk, entry, me) for entry in rest],
        ]
    )
    return AlertText(title=await _title(desk, first, me), body=body, lead_id=None, url="/dashboard")
