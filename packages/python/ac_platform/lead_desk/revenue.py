"""Revenue targets (owner meeting, 28 Oct 2026; Dipak's idea from a company he worked at):
each seller has a monthly revenue target, the system works out the calls it takes, and Home
shows a small bar. Built 31 Oct 2026 (migration 0150).

- **Revenue** is what Won leads were worth: a move to Won asks for the amount
  (``transitions.AMOUNT``), credited to the lead's owner. A lead won before amounts were
  asked, or placed Won by a file, counts as "amount not set" and is never guessed.
- **Targets** are per month: the organisation's (owners and managers set it) and each
  seller's. A seller without one gets an even share of the organisation's. Sellers may set
  their own when the workspace allows it.
- **What it takes**: the rest of the target ÷ the average deal = wins, then meetings,
  interested leads, connected calls and calls, from the workspace's own last 90 days, then
  calls per working day left. Until it has enough deals and calls of its own, typical rates
  (and the typical deal size the owner gives) stand in, shown as an estimate.

It is the customer's own revenue: our own plan prices never appear here.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ac_platform.lead_desk import hours as work_hours
from ac_platform.lead_desk.contracts import (
    DealAmountCommand,
    LeadDetail,
    RevenueBreakdownView,
    RevenueNeedsView,
    RevenueSettingsCommand,
    RevenueSplitLine,
    RevenueTargetLine,
    RevenueTargetsCommand,
    RevenueTargetsView,
    RevenueView,
    SellerRevenueView,
)
from ac_platform.lead_desk.errors import DeskError
from ac_platform.lead_desk.journey import transitions
from ac_platform.lead_desk.models import (
    Lead,
    LeadDealAmount,
    LeadDeskSettings,
    LeadEvent,
    LeadRevenueTarget,
)

if TYPE_CHECKING:
    from ac_platform.lead_desk.store import LeadDesk

IST: Final = ZoneInfo("Asia/Kolkata")
LOOKBACK: Final = timedelta(days=90)
# Before the workspace's own average deal and rates count.
MIN_DEALS: Final = 3
MIN_CALLS: Final = 50
MIN_STEP: Final = 10
# A typical inside-sales team: a win from three meetings, a meeting from about three
# interested leads, an interested lead from four connected calls, two calls in five
# connected. They give the owner's own example: ₹5 L at ₹1.25 L a deal is 4 wins, 12
# meetings, 40 interested and 400 calls, about 20 a day.
DEFAULT_RATES: Final = (1 / 3, 0.3, 0.25, 0.4)
# Monday to Saturday, where the workspace hasn't set its work days.
DEFAULT_DAYS: Final = (0, 1, 2, 3, 4, 5)
EVENT_ROWS: Final = 20000
SIDE_LABELS: Final = {"inbound": "Inbound", "cold": "Cold"}


@dataclass(frozen=True, slots=True)
class Rates:
    win_per_meeting: float
    meeting_per_interested: float
    interested_per_connected: float
    connected_per_call: float


@dataclass(frozen=True, slots=True)
class Counts:
    """The workspace's last 90 days."""

    calls: int = 0
    connected: int = 0
    interested: int = 0
    meetings: int = 0
    wins: int = 0


def rates_from(counts: Counts) -> tuple[Rates, bool]:
    """The workspace's own step rates, each one only once enough happened to trust it;
    otherwise the typical one. True when any typical rate stood in (an estimate)."""
    used_default = False

    def rate(top: int, bottom: int, default: float, enough: int = MIN_STEP) -> float:
        nonlocal used_default
        if bottom < enough or top <= 0:
            used_default = True
            return default
        return min(1.0, max(0.02, top / bottom))

    win, meeting, interested, connected = DEFAULT_RATES
    rates = Rates(
        win_per_meeting=rate(counts.wins, counts.meetings, win),
        meeting_per_interested=rate(counts.meetings, counts.interested, meeting),
        interested_per_connected=rate(counts.interested, counts.connected, interested),
        connected_per_call=rate(counts.connected, counts.calls, connected, MIN_CALLS),
    )
    return rates, used_default


def _up(value: float) -> int:
    # 3.0000000001 is 3, never 4.
    return max(0, math.ceil(round(value, 6)))


def what_it_takes(
    remaining: int, average_deal: int | None, rates: Rates, days_left: int, *, estimate: bool
) -> RevenueNeedsView | None:
    """Wins, meetings, interested leads, connected calls and calls to reach ``remaining``,
    and calls per working day left. None without an average deal to work from."""
    if not average_deal or average_deal <= 0:
        return None
    if remaining <= 0:
        return RevenueNeedsView(
            wins=0,
            meetings=0,
            interested=0,
            connected=0,
            calls=0,
            calls_per_day=0,
            working_days_left=days_left,
            average_deal=average_deal,
            estimate=estimate,
        )
    wins = _up(remaining / average_deal)
    meetings = _up(wins / rates.win_per_meeting)
    interested = _up(meetings / rates.meeting_per_interested)
    connected = _up(interested / rates.interested_per_connected)
    calls = _up(connected / rates.connected_per_call)
    return RevenueNeedsView(
        wins=wins,
        meetings=meetings,
        interested=interested,
        connected=connected,
        calls=calls,
        calls_per_day=_up(calls / max(1, days_left)),
        working_days_left=days_left,
        average_deal=average_deal,
        estimate=estimate,
    )


def month_of(moment: datetime) -> date:
    return moment.astimezone(IST).date().replace(day=1)


def next_month(month: date) -> date:
    return (month.replace(day=28) + timedelta(days=4)).replace(day=1)


def bounds(month: date) -> tuple[datetime, datetime]:
    """The month's first and next month's first moment, India time, as UTC."""
    start = datetime.combine(month, time.min, tzinfo=IST).astimezone(UTC)
    end = datetime.combine(next_month(month), time.min, tzinfo=IST).astimezone(UTC)
    return start, end


def month_gone(now: datetime, month: date) -> float:
    start, end = bounds(month)
    return round(min(1.0, max(0.0, (now - start) / (end - start))), 4)


def working_days_left(now: datetime, month: date, days: tuple[int, ...] | None) -> int:
    """Work days from today to the month's end, today included (India time)."""
    workdays = set(days or DEFAULT_DAYS)
    today = now.astimezone(IST).date()
    last = next_month(month) - timedelta(days=1)
    day = max(today, month)
    left = 0
    while day <= last:
        left += day.weekday() in workdays
        day += timedelta(days=1)
    return left


def even_split(organisation: int | None, sellers: int) -> int | None:
    if not organisation or sellers <= 0:
        return None
    return organisation // sellers


def settings_of(config: dict[str, Any]) -> tuple[bool, int | None]:
    """Whether sellers set their own target, and the typical deal size."""
    raw = config.get("revenue")
    revenue: dict[str, Any] = raw if isinstance(raw, dict) else {}
    typical = revenue.get("typical_deal")
    return (
        revenue.get("sellers_set_own") is True,
        typical if isinstance(typical, int) and typical > 0 else None,
    )


# ----- reads ---------------------------------------------------------------------------


async def _sellers(desk: LeadDesk) -> list[tuple[UUID, str]]:
    """Everyone who works leads here, by name (never ranked)."""
    from ac_platform.identity.models import Person
    from ac_platform.lead_desk.store import SELLER_ROLES, person_name
    from ac_platform.tenancy.models import Membership

    rows = (
        await desk.db.execute(
            select(Membership.person_id, Person)
            .join(Person, Person.id == Membership.person_id)
            .where(
                Membership.tenant_id == desk.tenant_id,
                Membership.status == "active",
                Membership.ended_at.is_(None),
                Membership.role.in_(SELLER_ROLES),
            )
        )
    ).all()
    found = [(row[0], person_name(row[1])) for row in rows]
    return sorted(found, key=lambda item: (item[1].lower(), str(item[0])))


async def _targets(desk: LeadDesk, month: date) -> tuple[int | None, dict[UUID, int]]:
    rows = (
        await desk.db.scalars(
            select(LeadRevenueTarget)
            .where(LeadRevenueTarget.tenant_id == desk.tenant_id, LeadRevenueTarget.month == month)
            .order_by(LeadRevenueTarget.created_at.desc(), LeadRevenueTarget.id)
        )
    ).all()
    newest: dict[UUID | None, int] = {}
    for row in rows:
        newest.setdefault(row.person_id, row.amount)
    organisation = newest.pop(None, 0) or None
    return organisation, {person: amount for person, amount in newest.items() if person and amount}


async def _test_filter(desk: LeadDesk) -> tuple[Any, ...]:
    # A sandbox organisation's own numbers count its test data; nobody else's do.
    return () if await desk._sandbox_organisation() else (Lead.test_data.is_(False),)


async def _deals(desk: LeadDesk, start: datetime, end: datetime) -> dict[UUID, LeadDealAmount]:
    """Each lead still Won with an amount won in the window: its newest amount."""
    rows = (
        await desk.db.scalars(
            select(LeadDealAmount)
            .join(Lead, Lead.id == LeadDealAmount.lead_id)
            .where(
                LeadDealAmount.tenant_id == desk.tenant_id,
                LeadDealAmount.won_at >= start,
                LeadDealAmount.won_at < end,
                Lead.tenant_id == desk.tenant_id,
                Lead.stage == "won",
                *await _test_filter(desk),
            )
            .order_by(LeadDealAmount.created_at.desc(), LeadDealAmount.id)
            .limit(EVENT_ROWS)
        )
    ).all()
    newest: dict[UUID, LeadDealAmount] = {}
    for row in rows:
        newest.setdefault(row.lead_id, row)
    return newest


def _won_move(data: Any) -> bool:
    """A person's move into Won (never a file's, a merge's or the stage list's)."""
    if not isinstance(data, dict):
        return False
    to = data.get("to_kind") if data.get("v") == 2 else data.get("stage")
    before = data.get("from_kind") if data.get("v") == 2 else data.get("from_stage")
    source = data.get("source")
    return (
        to == "won"
        and before != "won"
        and source
        not in (
            *transitions.PLACING,
            *transitions.BOOKKEEPING,
        )
    )


async def _not_set(
    desk: LeadDesk, start: datetime, end: datetime, priced: set[UUID]
) -> dict[UUID | None, int]:
    """Leads won in the window, still Won, with no amount: per credited seller."""
    rows = (
        await desk.db.execute(
            select(
                LeadEvent.lead_id, LeadEvent.actor_person_id, LeadEvent.data, Lead.owner_person_id
            )
            .join(Lead, Lead.id == LeadEvent.lead_id)
            .where(
                LeadEvent.tenant_id == desk.tenant_id,
                LeadEvent.kind.in_(("stage", "result")),
                LeadEvent.created_at >= start,
                LeadEvent.created_at < end,
                Lead.tenant_id == desk.tenant_id,
                Lead.stage == "won",
                *await _test_filter(desk),
            )
            .limit(EVENT_ROWS)
        )
    ).all()
    seen: dict[UUID, UUID | None] = {}
    for lead_id, actor, data, owner in rows:
        if lead_id not in priced and _won_move(data):
            seen[lead_id] = owner or actor
    out: dict[UUID | None, int] = defaultdict(int)
    for person in seen.values():
        out[person] += 1
    return out


async def _counts(desk: LeadDesk, start: datetime, end: datetime) -> Counts:
    """Calls, connected calls, interested leads, meetings and wins: the whole workspace."""
    from ac_platform.lead_desk.store import call_answered, call_out

    # Every seller's "what it takes" uses the whole workspace's rates: only totals leave here,
    # never a call, so they come straight from the call events, not the team's feed.
    calls = connected = 0
    for data in (
        await desk.db.scalars(
            select(LeadEvent.data)
            .where(
                LeadEvent.tenant_id == desk.tenant_id,
                LeadEvent.kind == "call",
                LeadEvent.created_at >= start,
                LeadEvent.created_at < end,
                LeadEvent.actor_person_id.is_not(None),
            )
            .limit(EVENT_ROWS)
        )
    ).all():
        if not isinstance(data, dict) or data.get("for_call") or data.get("simulated"):
            continue
        if call_out(data):
            calls += 1
            connected += call_answered(data)
    moves = (
        await desk.db.execute(
            select(LeadEvent.lead_id, LeadEvent.kind, LeadEvent.data)
            .where(
                LeadEvent.tenant_id == desk.tenant_id,
                LeadEvent.kind.in_(("result", "stage", "meeting")),
                LeadEvent.created_at >= start,
                LeadEvent.created_at < end,
                LeadEvent.actor_person_id.is_not(None),
            )
            .limit(EVENT_ROWS)
        )
    ).all()
    interested: set[UUID] = set()
    meetings: set[UUID] = set()
    won: set[UUID] = set()
    for lead_id, kind, raw in moves:
        data = raw if isinstance(raw, dict) else {}
        if kind == "meeting":
            if data.get("action") == "scheduled":
                meetings.add(lead_id)
            continue
        if transitions.stages_changed(data) or data.get("source") in transitions.PLACING:
            continue
        stage = data.get("stage") or data.get("to_kind")
        before = data.get("from_stage") or data.get("from_kind")
        if stage == "interested" and before != stage:
            interested.add(lead_id)
        if _won_move(data):
            won.add(lead_id)
    return Counts(calls, connected, len(interested), len(meetings), len(won))


async def _average_deal(desk: LeadDesk, typical: int | None) -> tuple[int | None, bool]:
    """The workspace's average deal over 90 days, or the typical deal it gave (an
    estimate) while it has fewer than three of its own."""
    deals = await _deals(desk, desk.now - LOOKBACK, desk.now + timedelta(seconds=1))
    if len(deals) >= MIN_DEALS:
        return round(sum(row.amount for row in deals.values()) / len(deals)), False
    return typical, True


async def revenue(desk: LeadDesk, scope: str) -> RevenueView:
    """This month's revenue against target: mine (the signed-in seller) or the team's
    (owners, managers and viewers), with what it takes to reach the rest."""
    if scope not in ("mine", "team"):
        raise DeskError(422, "Pick mine or team.")
    if scope == "team" and not desk.viewer.can_see_team:
        raise DeskError(403, "Only owners, admins and managers see the team's revenue.")
    config = (await desk.settings())[1]
    _, typical = settings_of(config)
    month = month_of(desk.now)
    start, end = bounds(month)
    sellers = await _sellers(desk)
    organisation, own = await _targets(desk, month)
    share = even_split(organisation, len(sellers))
    deals = await _deals(desk, start, end)
    not_set = await _not_set(desk, start, end, set(deals))
    won_by: dict[UUID | None, list[int]] = defaultdict(list)
    for row in deals.values():
        won_by[row.credited_person_id].append(row.amount)

    def line(person: UUID, name: str) -> SellerRevenueView:
        target, source = (own[person], "own") if person in own else (share, "split")
        return SellerRevenueView(
            person_id=person,
            name=name,
            target=target,
            target_source=source if target else None,
            won=sum(won_by.get(person, [])),
            deals=len(won_by.get(person, [])),
            amount_not_set=not_set.get(person, 0),
        )

    hours = work_hours.parse(config)
    days_left = working_days_left(desk.now, month, hours.days if hours else None)
    average, typical_used = await _average_deal(desk, typical)
    rates, default_rates = rates_from(await _counts(desk, desk.now - LOOKBACK, desk.now))
    estimate = typical_used or default_rates
    if scope == "mine":
        me = desk.viewer.person_id
        mine = line(me, desk.viewer.name)
        return RevenueView(
            scope="mine",
            month=month,
            currency="INR",
            month_gone=month_gone(desk.now, month),
            target=mine.target,
            target_source=mine.target_source,
            won=mine.won,
            deals=mine.deals,
            amount_not_set=mine.amount_not_set,
            needs=what_it_takes(
                (mine.target or 0) - mine.won, average, rates, days_left, estimate=estimate
            )
            if mine.target
            else None,
        )
    lines = tuple(line(person, name) for person, name in sellers)
    team_target = organisation or (sum(own.values()) or None)
    won = sum(row.amount for row in deals.values())
    return RevenueView(
        scope="team",
        month=month,
        currency="INR",
        month_gone=month_gone(desk.now, month),
        target=team_target,
        target_source=("organisation" if organisation else "sellers") if team_target else None,
        won=won,
        deals=len(deals),
        amount_not_set=sum(not_set.values()),
        needs=what_it_takes(team_target - won, average, rates, days_left, estimate=estimate)
        if team_target
        else None,
        sellers=lines,
    )


async def targets_view(desk: LeadDesk, month: date | None = None) -> RevenueTargetsView:
    """A month's targets as Team controls shows them: the organisation's, each seller's
    own or even share, and the workspace's two settings. A seller sees only their own."""
    wanted = _month(desk, month)
    revision, config = await desk.settings()
    set_own, typical = settings_of(config)
    sellers = await _sellers(desk)
    organisation, own = await _targets(desk, wanted)
    share = even_split(organisation, len(sellers))
    team = desk.viewer.can_see_team
    return RevenueTargetsView(
        month=wanted,
        currency="INR",
        organisation=organisation,
        sellers=tuple(
            RevenueTargetLine(
                person_id=person,
                name=name,
                own=own.get(person),
                split=None if person in own else share,
            )
            for person, name in sellers
            if team or person == desk.viewer.person_id
        ),
        sellers_set_own=set_own,
        typical_deal=typical,
        revision=revision,
        can_manage=desk.viewer.can_manage,
    )


def _month(desk: LeadDesk, month: date | None) -> date:
    this = month_of(desk.now)
    if month is None:
        return this
    if month.day != 1:
        raise DeskError(422, "Pick a month.")
    if month < this or month > next_month(next_month(this)):
        raise DeskError(422, "Set this month's target or the next two months'.")
    return month


async def set_targets(desk: LeadDesk, command: RevenueTargetsCommand) -> RevenueTargetsView:
    """Owners and managers set the organisation's target and any seller's; a seller sets
    their own when the workspace allows it. Each line is a new row, idempotent by the
    command; 0 clears it."""
    month = _month(desk, command.month)
    set_own, _ = settings_of((await desk.settings())[1])
    me = desk.viewer.person_id
    if not desk.viewer.can_manage:
        if command.organisation is not None:
            raise DeskError(403, "Only owners and managers set the organisation's target.")
        if not set_own or any(line.person_id != me for line in command.sellers):
            raise DeskError(403, "Your owner sets your target.")
    people = {person for person, _ in await _sellers(desk)}
    if any(line.person_id not in people for line in command.sellers):
        raise DeskError(422, "Choose someone who sells in this workspace.")
    wanted: list[tuple[UUID | None, int]] = []
    if command.organisation is not None:
        wanted.append((None, command.organisation))
    wanted += [(line.person_id, line.amount) for line in command.sellers]
    for person, amount in wanted:
        row_id = uuid5(command.command_id, str(person or "organisation"))
        if await desk.db.get(LeadRevenueTarget, row_id) is not None:
            continue
        desk.db.add(
            LeadRevenueTarget(
                id=row_id,
                tenant_id=desk.tenant_id,
                month=month,
                person_id=person,
                amount=amount,
                currency="INR",
                set_by_person_id=me,
                command_id=row_id,
                created_at=desk.now,
            )
        )
    await desk.db.flush()
    return await targets_view(desk, month)


async def save_settings(desk: LeadDesk, command: RevenueSettingsCommand) -> RevenueTargetsView:
    """Whether sellers set their own target, and the typical deal size (managers)."""
    desk._require_manager()
    row = await desk.db.get(LeadDeskSettings, desk.tenant_id, with_for_update=True)
    current = row.revision if row else 0
    if current != command.expected_revision:
        raise DeskError(409, "Someone changed these settings. Reload and try again.")
    config = dict(row.config) if row else {}
    config["revenue"] = {
        **dict(config.get("revenue") or {}),
        "sellers_set_own": command.sellers_set_own,
        "typical_deal": command.typical_deal,
    }
    if row is None:
        row = LeadDeskSettings(tenant_id=desk.tenant_id, revision=0, config={})
        desk.db.add(row)
    row.revision = current + 1
    row.config = config
    row.updated_by_person_id = desk.viewer.person_id
    row.updated_at = desk.now
    await desk.db.flush()
    return await targets_view(desk)


async def set_amount(desk: LeadDesk, lead_id: UUID, command: DealAmountCommand) -> LeadDetail:
    """Add or correct what a Won lead was worth (its owner or a manager): a new row; the
    lead keeps the time it was won."""
    found = await desk.db.scalar(
        select(LeadDealAmount.lead_id).where(
            LeadDealAmount.tenant_id == desk.tenant_id,
            LeadDealAmount.command_id == command.command_id,
        )
    )
    if found is not None:
        if found != lead_id:
            raise DeskError(409, "That request was already used for another lead.")
        return await desk.detail(lead_id)
    lead = await desk._lead(lead_id, lock=True)
    if not (desk.viewer.can_manage or lead.owner_person_id == desk.viewer.person_id):
        raise DeskError(403, "Only the lead's owner or a manager can set its amount.")
    if lead.stage != "won":
        raise DeskError(409, "Only a Won lead has a deal amount.")
    earlier = await desk.db.scalar(
        select(LeadDealAmount.won_at)
        .where(LeadDealAmount.tenant_id == desk.tenant_id, LeadDealAmount.lead_id == lead.id)
        .order_by(LeadDealAmount.created_at.desc())
        .limit(1)
    )
    desk._deal_amount(
        lead,
        command.amount,
        at=earlier or lead.stage_at or desk.now,
        event=None,
        by=desk.viewer.person_id,
        command_id=command.command_id,
    )
    await desk.db.flush()
    return await desk.detail(lead.id)


async def breakdown(desk: LeadDesk, days: int) -> RevenueBreakdownView:
    """Revenue won in the last 7, 30 or 90 days by seller and by side (Growth,
    Analytics): the team's for those who see the team, a seller's own otherwise."""
    if days not in (7, 30, 90):
        raise DeskError(422, "Pick 7, 30 or 90 days.")
    last = desk.now.astimezone(IST).date()
    start = datetime.combine(last - timedelta(days=days - 1), time.min, tzinfo=IST)
    start = start.astimezone(UTC)
    end = desk.now + timedelta(seconds=1)
    deals = await _deals(desk, start, end)
    not_set = await _not_set(desk, start, end, set(deals))
    team = desk.viewer.can_see_team
    me = desk.viewer.person_id
    rows = [row for row in deals.values() if team or row.credited_person_id == me]
    names = await desk._names(row.credited_person_id for row in rows)
    by_seller: dict[str, list[int]] = defaultdict(list)
    by_side: dict[str, list[int]] = {"inbound": [], "cold": []}
    for row in rows:
        by_seller[str(row.credited_person_id or "")].append(row.amount)
        by_side.setdefault(row.side, []).append(row.amount)
    sellers = sorted(
        (
            RevenueSplitLine(
                key=key,
                label=names.get(UUID(key), "Someone who left") if key else "No owner",
                won=sum(amounts),
                deals=len(amounts),
            )
            for key, amounts in by_seller.items()
        ),
        key=lambda line: line.label.lower(),
    )
    return RevenueBreakdownView(
        days=days,
        currency="INR",
        won=sum(row.amount for row in rows),
        deals=len(rows),
        amount_not_set=sum(not_set.values()) if team else not_set.get(me, 0),
        by_seller=tuple(sellers),
        by_side=tuple(
            RevenueSplitLine(
                key=side, label=SIDE_LABELS[side], won=sum(by_side[side]), deals=len(by_side[side])
            )
            for side in ("inbound", "cold")
        ),
    )
