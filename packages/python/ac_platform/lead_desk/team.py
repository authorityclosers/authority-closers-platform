"""The team engine on the database: targets, progress from real activity (team engine,
section 2; docs/product/lead-desk/team-engine.md).

- A seller's activity becomes ``targets.Fact`` rows: a call (the phone's log, or a call
  logged in the app) and its outcome on the same lead within two hours are one call; an
  outcome on a lead whose follow-up was due, and a task done, are follow-ups done (as
  Home's "Follow-ups done" counts them); a meeting booked is a meeting.
- Targets are rows that supersede from a day on: the newest row from that day back for each
  metric and period counts. Owners and managers set them; a seller reads their own.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID, uuid5

from sqlalchemy import and_, func, or_, select

from ac_platform.lead_desk import distribute as spread
from ac_platform.lead_desk import hours as work_hours
from ac_platform.lead_desk import my_day as day_plan
from ac_platform.lead_desk import next_best
from ac_platform.lead_desk import nudges as nudge_rules
from ac_platform.lead_desk import targets as goals
from ac_platform.lead_desk.contracts import (
    AlertText,
    DistributedTo,
    DistributeLeads,
    Distribution,
    MetricProgressView,
    MyDayFallback,
    MyDayItem,
    MyDayView,
    NudgesCommand,
    SellerTargets,
    TargetLine,
    TargetsCommand,
    Team,
    TouchedItem,
    UpcomingItem,
)
from ac_platform.lead_desk.errors import DeskError
from ac_platform.lead_desk.models import (
    Lead,
    LeadDeskSettings,
    LeadEvent,
    LeadNudge,
    LeadTarget,
    LeadTask,
)
from ac_platform.lead_desk.vocabulary import OPEN_STAGES, SOURCE_LABELS
from ac_platform.tenancy.models import Membership

if TYPE_CHECKING:
    from ac_platform.lead_desk.store import LeadDesk

# My day: work due within this time counts as "now"; a new lead's first-call target.
DUE_SOON: Final = timedelta(hours=2)
FIRST_CALL_MINUTES: Final = 5.0
TASK_WHAT: Final = {
    "call_back": "Call back",
    "whatsapp": "WhatsApp",
    "email": "Email",
    "send_file": "Send a file",
    "meeting": "Meeting",
    "other": "To do",
}
# A call and its outcome on the same lead within this time are one call.
CALL_PAIR: Final = timedelta(hours=2)
ACTIVITY_KINDS: Final = ("call", "result", "task", "meeting")


def _when(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def facts_from(events: Sequence[tuple[UUID, str, dict[str, Any], datetime]]) -> list[goals.Fact]:
    """Activity as facts: (lead, kind, data, at) rows of one seller, any order."""
    out: list[goals.Fact] = []
    calls: dict[UUID, list[tuple[datetime, str, bool]]] = defaultdict(list)
    for lead_id, kind, data, at in sorted(events, key=lambda item: item[3]):
        if kind == "call":
            key = f"{lead_id}:{at.isoformat()}"
            calls[lead_id].append((at, key, data.get("connected") is True))
            out.append(goals.Fact("call", at, call=key))
        elif kind == "result":
            # The latest call on the lead within the window, not yet paired, is this one.
            open_calls = calls.get(lead_id, [])
            paired = next(
                (item for item in reversed(open_calls) if at - item[0] <= CALL_PAIR), None
            )
            if paired is not None:
                open_calls.remove(paired)
            out.append(
                goals.Fact(
                    "result",
                    at,
                    call=paired[1] if paired else None,
                    connected=data.get("connected") is True,
                )
            )
            if data.get("was_due") is True:
                out.append(goals.Fact("follow_up", at))
        elif kind == "task" and data.get("action") == "done":
            out.append(goals.Fact("follow_up", at))
        elif kind == "meeting" and data.get("action") == "scheduled":
            out.append(goals.Fact("meeting_booked", at))
    # A call the phone logged as talked, with no outcome saved: still a connect.
    for open_calls in calls.values():
        for at, key, talked in open_calls:
            if talked:
                out.append(goals.Fact("result", at, call=key, connected=True))
    return out


async def facts(desk: LeadDesk, person: UUID, since: datetime) -> list[goals.Fact]:
    rows = (
        await desk.db.execute(
            select(LeadEvent.lead_id, LeadEvent.kind, LeadEvent.data, LeadEvent.created_at)
            .join(Lead, and_(Lead.id == LeadEvent.lead_id, Lead.tenant_id == LeadEvent.tenant_id))
            .where(
                LeadEvent.tenant_id == desk.tenant_id,
                LeadEvent.actor_person_id == person,
                LeadEvent.kind.in_(ACTIVITY_KINDS),
                LeadEvent.created_at >= since - CALL_PAIR,
                LeadEvent.created_at <= desk.now,
            )
        )
    ).tuples()
    return facts_from([(lead, kind, dict(data or {}), at) for lead, kind, data, at in rows])


async def work_hours_of(desk: LeadDesk) -> work_hours.WorkHours | None:
    return work_hours.parse((await desk.settings())[1])


async def targets_on(desk: LeadDesk, person: UUID, day: date) -> list[goals.Target]:
    """The seller's targets as they stood on ``day``: the newest row from it back, per
    metric and period; a zero is no target."""
    rows = (
        await desk.db.scalars(
            select(LeadTarget)
            .where(
                LeadTarget.tenant_id == desk.tenant_id,
                LeadTarget.person_id == person,
                LeadTarget.effective_from <= day,
            )
            .order_by(LeadTarget.effective_from.desc(), LeadTarget.created_at.desc())
        )
    ).all()
    seen: dict[tuple[str, str], LeadTarget] = {}
    for row in rows:
        seen.setdefault((row.metric, row.period), row)
    return [
        goals.Target(row.metric, row.period, row.value)  # type: ignore[arg-type]
        for row in sorted(
            seen.values(),
            key=lambda item: (goals.METRICS.index(item.metric), item.period),
        )
        if row.value > 0
    ]


def _may_see(desk: LeadDesk, person: UUID) -> None:
    if person != desk.viewer.person_id and not desk.viewer.can_manage:
        raise DeskError(403, "Only owners and admins see someone else's targets.")


async def seller_targets(desk: LeadDesk, person: UUID | None = None) -> SellerTargets:
    """A seller's targets today, and their progress against each."""
    who = person or desk.viewer.person_id
    _may_see(desk, who)
    today = goals.day_start(desk.now).date()
    wanted = await targets_on(desk, who, today)
    hours = await work_hours_of(desk)
    done = await facts(desk, who, goals.week_start(desk.now))
    progress = goals.progress(done, wanted, hours, desk.now)
    return SellerTargets(
        person_id=who,
        targets=tuple(
            TargetLine(metric=item.metric, period=item.period, value=item.value) for item in wanted
        ),
        progress=tuple(
            MetricProgressView(
                metric=item.metric,
                period=item.period,
                target=item.target,
                done=item.done,
                pace=round(item.pace, 4),
                expected=round(item.expected, 2),
                behind=item.behind,
                short=item.short,
            )
            for item in progress
        ),
    )


async def set_targets(desk: LeadDesk, command: TargetsCommand) -> SellerTargets:
    """An owner or manager sets a seller's targets from a day on (today by default). Each
    line is a new row, idempotent by the command; a value of 0 removes that target."""
    desk._require_manager()
    await desk._require_seller(command.person_id)
    today = goals.day_start(desk.now).date()
    start = command.effective_from or today
    if start < today:
        raise DeskError(422, "Targets start today or later; the past keeps its own.")
    for line in command.targets:
        row_id = uuid5(command.command_id, f"{line.metric}:{line.period}")
        if await desk.db.get(LeadTarget, row_id) is not None:
            continue
        desk.db.add(
            LeadTarget(
                id=row_id,
                tenant_id=desk.tenant_id,
                person_id=command.person_id,
                period=line.period,
                metric=line.metric,
                value=line.value,
                effective_from=start,
                set_by_person_id=desk.viewer.person_id,
                command_id=row_id,
                created_at=desk.now,
            )
        )
    await desk.db.flush()
    return await seller_targets(desk, command.person_id)


async def team_progress(desk: LeadDesk) -> tuple[SellerTargets, ...]:
    """Every seller with targets, for the owner's Team view."""
    desk._require_manager()
    today = goals.day_start(desk.now).date()
    people = (
        await desk.db.scalars(
            select(LeadTarget.person_id)
            .where(LeadTarget.tenant_id == desk.tenant_id, LeadTarget.effective_from <= today)
            .distinct()
        )
    ).all()
    out = [await seller_targets(desk, person) for person in sorted(people)]
    return tuple(item for item in out if item.targets)


def nudges_on(config: dict[str, Any] | None, person: UUID) -> bool:
    """Whether this seller gets nudges: on for the workspace and not off for them."""
    team = dict((config or {}).get("team") or {})
    off = {str(item) for item in team.get("nudges_off_for") or []}
    return bool(team.get("nudges")) and str(person) not in off


def _numbers(found: Sequence[goals.Fact], since: datetime, until: datetime) -> dict[str, int]:
    window = [fact for fact in found if since <= fact.at < until]
    return {metric: goals.count(window, metric) for metric in goals.METRICS}


def _progress_views(items: Sequence[goals.MetricProgress]) -> tuple[MetricProgressView, ...]:
    return tuple(
        MetricProgressView(
            metric=item.metric,
            period=item.period,
            target=item.target,
            done=item.done,
            pace=round(item.pace, 4),
            expected=round(item.expected, 2),
            behind=item.behind,
            short=item.short,
        )
        for item in items
    )


async def my_day_for(desk: LeadDesk, person: UUID | None = None) -> MyDayView:
    """The seller's work, ranked, today's numbers and targets, and what to show when today
    is empty (team engine, section 4)."""
    who = person or desk.viewer.person_id
    _may_see(desk, who)
    now = desk.now
    soon = now + DUE_SOON
    mine = and_(
        Lead.tenant_id == desk.tenant_id,
        Lead.owner_person_id == who,
        Lead.stage.in_(OPEN_STAGES),
    )
    tasks = (
        await desk.db.execute(
            select(LeadTask, Lead.name)
            .join(Lead, and_(Lead.id == LeadTask.lead_id, Lead.tenant_id == LeadTask.tenant_id))
            .where(
                LeadTask.tenant_id == desk.tenant_id,
                LeadTask.owner_person_id == who,
                LeadTask.status == "open",
            )
            .order_by(LeadTask.starts_at)
            .limit(200)
        )
    ).all()
    tasked = {task.lead_id for task, _ in tasks}
    leads = (
        await desk.db.scalars(
            select(Lead)
            .where(
                mine,
                or_(
                    Lead.next_action_at <= soon,
                    and_(Lead.stage == "new", Lead.next_action_at.is_(None)),
                ),
            )
            .order_by(Lead.next_action_at, Lead.created_at)
            .limit(200)
        )
    ).all()
    missed = await desk._waiting_call_back() if who == desk.viewer.person_id else {}
    candidates: list[next_best.Candidate] = [
        next_best.Candidate(
            str(task.lead_id),
            name,
            task_id=str(task.id),
            due_at=task.starts_at,
            promised=True,
            missed_caller=task.lead_id in missed,
        )
        for task, name in tasks
        if task.starts_at <= soon
    ]
    for lead in leads:
        if lead.id in tasked:
            continue
        fresh = lead.stage == "new" and lead.next_action_at is None
        candidates.append(
            next_best.Candidate(
                str(lead.id),
                lead.name,
                due_at=lead.next_action_at,
                missed_caller=lead.id in missed,
                waiting_minutes=(now - lead.created_at).total_seconds() / 60 if fresh else None,
                target_minutes=FIRST_CALL_MINUTES if fresh else None,
            )
        )
    week = goals.week_start(now)
    until = now + timedelta(seconds=1)
    found = await facts(desk, who, week - timedelta(days=7))
    wanted = await targets_on(desk, who, goals.day_start(now).date())
    later_calls = (
        await desk.db.scalars(
            select(Lead)
            .where(mine, Lead.next_action_at > soon)
            .order_by(Lead.next_action_at)
            .limit(6)
        )
    ).all()
    recent = (
        await desk.db.scalars(
            select(Lead)
            .where(
                Lead.tenant_id == desk.tenant_id,
                Lead.owner_person_id == who,
                Lead.last_contact_at.is_not(None),
            )
            .order_by(Lead.last_contact_at.desc())
            .limit(day_plan.RECENT)
        )
    ).all()
    plan = day_plan.my_day(
        candidates,
        today=_numbers(found, goals.day_start(now), until),
        week=_numbers(found, week, until),
        last_week=_numbers(found, week - timedelta(days=7), week),
        progress=goals.progress(found, wanted, await work_hours_of(desk), now),
        upcoming=[
            *(
                day_plan.Upcoming(
                    str(task.lead_id), name, task.starts_at, TASK_WHAT.get(task.kind, "To do")
                )
                for task, name in tasks
                if task.starts_at > soon
            ),
            *(
                day_plan.Upcoming(str(lead.id), lead.name, lead.next_action_at, "Call")
                for lead in later_calls
                if lead.next_action_at is not None and lead.id not in tasked
            ),
        ],
        recent=[
            day_plan.Touched(str(lead.id), lead.name, lead.last_contact_at, lead.last_result)
            for lead in recent
            if lead.last_contact_at is not None
        ],
        now=now,
    )
    fallback = plan.fallback
    return MyDayView(
        person_id=who,
        do_now=tuple(
            MyDayItem(
                lead_id=UUID(item.candidate.lead_id),
                lead_name=item.candidate.lead_name,
                task_id=UUID(item.candidate.task_id) if item.candidate.task_id else None,
                due_at=item.candidate.due_at,
                score=round(item.score, 4),
                because=item.because,
            )
            for item in plan.do_now
        ),
        today=dict(plan.today),
        progress=_progress_views(plan.progress),
        fallback=None
        if fallback is None
        else MyDayFallback(
            next_up=tuple(
                UpcomingItem(
                    lead_id=UUID(item.lead_id), lead_name=item.lead_name, at=item.at, what=item.what
                )
                for item in fallback.next_up
            ),
            week=dict(fallback.week),
            last_week=dict(fallback.last_week),
            recent=tuple(
                TouchedItem(
                    lead_id=UUID(item.lead_id),
                    lead_name=item.lead_name,
                    at=item.at,
                    outcome=item.outcome,
                )
                for item in fallback.recent
            ),
        ),
    )


# ----- distribution (section 1) ----------------------------------------------------------

LEFT_WORDS: Final = {
    "closed": "closed",
    "already_theirs": "already with a chosen seller",
    "no_seller_for_it": "no seller for their source or city",
    "everyone_at_cap": "everyone at their cap",
    "gone": "not found",
}
GROUPS_SHOWN: Final = 50


def _source_of(lead: Lead) -> str:
    return lead.source_label or SOURCE_LABELS.get(lead.source, lead.source)


def _seen(values: Sequence[str | None]) -> dict[str, int]:
    """Each value with how many, first spelling kept, the most common first."""
    counts: dict[str, int] = {}
    spelling: dict[str, str] = {}
    for value in values:
        key = " ".join((value or "").lower().split())
        if not key:
            continue
        spelling.setdefault(key, " ".join((value or "").split()))
        counts[key] = counts.get(key, 0) + 1
    ranked = sorted(counts, key=lambda key: (-counts[key], key))[:GROUPS_SHOWN]
    return {spelling[key]: counts[key] for key in ranked}


def _distribution_words(moved: int, left: dict[str, int], *, preview: bool) -> str:
    leads = f"{moved} lead{'' if moved == 1 else 's'}"
    said = (
        (f"{leads} would move." if preview else f"{leads} given out.")
        if moved
        else ("No lead would move." if preview else "No lead moved.")
    )
    stay = sum(left.values())
    if stay:
        why = ", ".join(
            f"{count} {LEFT_WORDS.get(reason, reason)}"
            for reason, count in sorted(left.items(), key=lambda item: -item[1])
        )
        said += f" {stay} stay where they are: {why}."
    return said


async def distribute_leads(desk: LeadDesk, command: DistributeLeads) -> Distribution:
    """Give chosen or unassigned leads out by a rule; a preview changes nothing (team
    engine, section 1). Each move is a manager's move, one history line each, and a retry
    of the same command returns what it did."""
    desk._require_manager()
    if bool(command.lead_ids) == command.unassigned:
        raise DeskError(422, "Choose some leads, or all unassigned leads.")
    by_group = command.rule in ("by_source", "by_city")
    if by_group and not any(command.groups.values()):
        raise DeskError(422, "Choose who takes each source or city.")
    if not command.preview:
        seen = await desk._command_seen(command.command_id)
        if seen is not None:
            done = seen.data.get("distribution")
            if not isinstance(done, dict):
                raise DeskError(409, "This request was already used. Try again.")
            return Distribution.model_validate(done)
    reps = {rep.state.person_id: rep.state for rep in await desk._reps()}
    if by_group:
        people = list(
            dict.fromkeys(person for group in command.groups.values() for person in group)
        )
    else:
        people = list(dict.fromkeys(command.sellers)) or [
            person for person, state in reps.items() if state.available
        ]
    if not people:
        raise DeskError(422, "Nobody is taking leads. Choose at least one seller.")
    if any(person not in reps for person in people):
        raise DeskError(422, "Choose people who are active members of this workspace.")

    query = select(Lead).where(Lead.tenant_id == desk.tenant_id)
    if command.unassigned:
        query = (
            query.where(Lead.owner_person_id.is_(None), Lead.stage.in_(OPEN_STAGES))
            .order_by(Lead.created_at, Lead.id)
            .limit(spread.LIMIT + 1)
        )
    else:
        query = query.where(Lead.id.in_(command.lead_ids))
    if not command.preview:
        query = query.with_for_update()
    found = list((await desk.db.scalars(query)).all())
    more = len(found) > spread.LIMIT
    found = found[: spread.LIMIT]
    gone = 0
    if not command.unassigned:
        place = {lead_id: index for index, lead_id in enumerate(dict.fromkeys(command.lead_ids))}
        found.sort(key=lambda lead: place[lead.id])
        gone = len(place) - len(found)

    plan = spread.distribute(
        [
            spread.LeadSpot(lead.id, lead.stage, lead.owner_person_id, _source_of(lead), lead.city)
            for lead in found
        ],
        [
            spread.Seller(person, reps[person].open_leads, reps[person].max_open)
            for person in people
        ],
        command.rule,
        groups=command.groups if by_group else None,
        spread_all=command.spread_all,
    )
    left = dict(plan.left)
    if gone:
        left["gone"] = gone
    arriving: dict[UUID, int] = defaultdict(int)
    leaving: dict[UUID, int] = defaultdict(int)
    for move in plan.moves:
        arriving[move.to] += 1
        if move.previous is not None:
            leaving[move.previous] += 1
    still_open = [lead for lead in found if lead.stage in OPEN_STAGES]
    view = Distribution(
        rule=command.rule,
        preview=command.preview,
        leads=len(found) + gone,
        moved=len(plan.moves),
        given=tuple(
            DistributedTo(
                person_id=person,
                name=reps[person].name,
                leads=plan.given.get(person, 0),
                open_after=reps[person].open_leads + arriving[person] - leaving[person],
                max_open=reps[person].max_open,
            )
            for person in people
        ),
        left=left,
        sources=_seen([_source_of(lead) for lead in still_open]),
        cities=_seen([lead.city for lead in still_open]),
        more=more,
        words=_distribution_words(len(plan.moves), left, preview=command.preview),
    )
    if command.preview or not plan.moves:
        return view
    leads = {lead.id: lead for lead in found}
    reason = f"Distributed: {spread.RULE_WORDS[command.rule]}"
    for index, move in enumerate(plan.moves):
        event = await desk._set_owner(
            leads[move.lead_id],
            move.to,
            reason,
            "distribute",
            actor=desk.viewer.person_id,
            kind="reassigned",
            # The first move carries the command and what it did, so a retry returns it.
            command_id=command.command_id
            if index == 0
            else uuid5(command.command_id, str(move.lead_id)),
        )
        if index == 0:
            event.data = {
                **event.data,
                "distribution": view.model_dump(mode="json", by_alias=True),
            }
    await desk.db.flush()
    return view


# ----- nudges (section 3) ------------------------------------------------------------

NUDGE_TITLES: Final = {"drift": "Behind pace", "idle": "Leads waiting"}


async def save_nudges(desk: LeadDesk, command: NudgesCommand) -> Team:
    """An owner or manager turns nudges on for the workspace (off by default) and off for
    chosen sellers."""
    desk._require_manager()
    off = sorted({str(person) for person in command.off_for})
    members = {str(rep.state.person_id) for rep in await desk._reps()}
    if any(person not in members for person in off):
        raise DeskError(422, "Choose people who are active members of this workspace.")
    row = await desk.db.get(LeadDeskSettings, desk.tenant_id, with_for_update=True)
    current = row.revision if row else 0
    if current != command.expected_revision:
        raise DeskError(409, "Someone changed these settings. Reload and try again.")
    config = dict(row.config) if row else {}
    config["team"] = {
        **dict(config.get("team") or {}),
        "nudges": command.enabled,
        "nudges_off_for": off,
    }
    if row is None:
        row = LeadDeskSettings(tenant_id=desk.tenant_id, revision=0, config={})
        desk.db.add(row)
    row.revision = current + 1
    row.config = config
    row.updated_by_person_id = desk.viewer.person_id
    row.updated_at = desk.now
    await desk.db.flush()
    return await desk.team()


async def nudge_now(desk: LeadDesk) -> tuple[nudge_rules.Nudge, int] | None:
    """The nudge the desk's seller should get now, with how much work waits, or None.
    Cheap first: with nudges off, outside work, or with this window or the day's three
    already sent, nothing else is read."""
    person = desk.viewer.person_id
    config = (await desk.settings())[1]
    if not nudges_on(config, person):
        return None
    hours = work_hours.parse(config)
    window = nudge_rules.window_start(hours, desk.now)
    if window is None:
        return None
    day = goals.day_start(desk.now)
    sent = list(
        (
            await desk.db.scalars(
                select(LeadNudge.window_start).where(
                    LeadNudge.tenant_id == desk.tenant_id,
                    LeadNudge.person_id == person,
                    LeadNudge.window_start >= day,
                )
            )
        ).all()
    )
    if window in sent or len(sent) >= nudge_rules.PER_DAY:
        return None
    found = await facts(desk, person, goals.week_start(desk.now))
    wanted = await targets_on(desk, person, day.date())
    last_activity = await desk.db.scalar(
        select(func.max(LeadEvent.created_at)).where(
            LeadEvent.tenant_id == desk.tenant_id,
            LeadEvent.actor_person_id == person,
            LeadEvent.created_at >= day,
            LeadEvent.created_at <= desk.now,
        )
    )
    last_call = max(
        (fact.at for fact in found if fact.kind in ("call", "result") and fact.at <= desk.now),
        default=None,
    )
    due = (await desk.badge()).to_call
    chosen = nudge_rules.nudge(
        goals.progress(found, wanted, hours, desk.now),
        last_activity=last_activity,
        last_call=last_call,
        due_work=due,
        hours=hours,
        sent=sent,
        now=desk.now,
    )
    return None if chosen is None else (chosen, due)


async def nudge_words(desk: LeadDesk) -> AlertText:
    """The words on the seller's latest nudge today, read by the app on their session. From
    any workspace they still work in, not only the one open: a seller in a personal
    workspace and an organisation gets the organisation's nudge words either way (Android,
    25 Oct 2026)."""
    latest = await desk.db.scalar(
        select(LeadNudge)
        .join(
            Membership,
            and_(
                Membership.tenant_id == LeadNudge.tenant_id,
                Membership.person_id == LeadNudge.person_id,
            ),
        )
        .where(
            LeadNudge.person_id == desk.viewer.person_id,
            LeadNudge.window_start >= goals.day_start(desk.now),
            Membership.status == "active",
            Membership.ended_at.is_(None),
        )
        .order_by(LeadNudge.claimed_at.desc())
        .limit(1)
    )
    if latest is None:
        return AlertText(
            title="Back to your leads",
            body="Open Sales Xray to see what's next.",
            lead_id=None,
            url="/leads",
            urgency="urgent",
        )
    return AlertText(
        title=NUDGE_TITLES.get(latest.kind, "Back to your leads"),
        body=latest.words,
        lead_id=None,
        url="/leads?nudge=1",
        urgency="urgent",
    )
