"""The outreach log, the touch counter and the cadence guard (v1.95, owner 22 Nov 2026: "every
person we contact is a lead, every message we send them is tracked, so we never feel spammy";
spec boards/sx-redesign/review/v195-outreach-log-spec.md; migration 0166).

A **touch** is one message, call, file or quote we send a lead, from Sales X-Ray itself (a
seller's WhatsApp or SMS link, a Cloud API send, an automation, a call, "Log a touch") or from
an outside sender through the public API (integrations/outreach_api.py). Every touch keeps or
makes exactly one line in the lead's timeline (``lead_desk_events``, kinds message, email and
call); its row in ``lead_desk_touches`` holds what the timeline cannot: who sent it, our own
short summary (never the lead's words), the provider and its delivery state, the reply that
answered it, whether it counted toward the limits and the guard's verdict when it went.

The **guard** (``guard``, pure: time, settings and facts passed in) answers, for one lead and
one channel, ok, warn or block with the reasons and when waiting would help:

1. a STOP on this channel blocks, and nothing overrides it;
2. a lead in the Bin, or test data for an automation or outside sender, blocks; an archived
   lead or one kept as history warns;
3. the lead wrote to us in the last 24 hours on this channel: ok and uncounted (a
   conversation is never spam);
4. counted touches since the start of today, in the workspace's time zone, at the day limit
   (1); 5. in the last 7×24 hours at the week limit (3); 6. that many unanswered in a row
   (3), then the lead rests (14 days): each gives the channel's mode (off, show, warn,
   block; WhatsApp splits people and automations);
7. outside the sending hours (the outreach hours set, else the team's work hours, else
   10:00-20:00 Mon-Sat): people are warned, automations held;
8. a manager's unused "send anyway" for this lead and channel turns warn or block into ok,
   once, for 30 minutes (``grant_override``).

What counts: touches we start (not replies in the 24-hour window), not failed, expired or a
released reservation, on a channel whose mode is not off, to someone who is not internal.
WhatsApp, SMS, email, Messenger, Instagram, files and quotes count together; calls and
in-person hand-overs count only when their mode is warn or block (repeat dials are normal
sales work).

Settings live in ``lead_desk_settings.config["outreach"]`` (Lead rules › Outreach limits).
Audit events carry ids, counts and field names only: never message words, phones or emails.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any, Final, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.service import AuditRepository
from ac_platform.identity.models import Person
from ac_platform.lead_desk import hours as work_hours
from ac_platform.lead_desk.capture import first_email, normalise_phone
from ac_platform.lead_desk.contracts import (
    BulkGuard,
    BulkGuardCommand,
    BulkGuardLead,
    LeadDefaults,
    OutreachChannelMode,
    OutreachCounts,
    OutreachGuard,
    OutreachReason,
    OutreachRules,
    OutreachRulesCommand,
    OverrideCommand,
    OverrideHint,
    OverrideView,
    SenderCommand,
    SenderEdit,
    SenderPause,
    Senders,
    SenderView,
    SendHours,
    TouchCommand,
    TouchLogged,
    TouchPage,
    TouchView,
)
from ac_platform.lead_desk.errors import DeskError
from ac_platform.lead_desk.history import HISTORY
from ac_platform.lead_desk.models import (
    Lead,
    LeadDeskSettings,
    LeadEvent,
    LeadOutreachSender,
    LeadSocialMessage,
    LeadTouch,
    LeadTouchOverride,
    LeadTouchReply,
    LeadWhatsAppMessage,
)
from ac_platform.tenancy.models import Membership
from ac_platform.tenancy.roles import can

if TYPE_CHECKING:
    from ac_platform.lead_desk.store import LeadDesk

IST: Final = ZoneInfo("Asia/Kolkata")
KEY: Final = "outreach"
AUDIT_RESOURCE: Final = "lead_desk.outreach"
CHANNELS: Final = (
    "whatsapp",
    "sms",
    "email",
    "call",
    "messenger",
    "instagram",
    "in_person",
    "other",
)
CHANNEL_WORDS: Final[dict[str, str]] = {
    "whatsapp": "WhatsApp",
    "sms": "SMS",
    "email": "email",
    "call": "calls",
    "messenger": "Messenger",
    "instagram": "Instagram",
    "in_person": "in person",
    "other": "other",
}
MODES: Final = ("off", "show", "warn", "block")
# Counted only when their mode is warn or block (calls, a PDF handed over in person).
SHOWN_ONLY: Final = frozenset({"call", "in_person"})
DEFAULT_MODES: Final[dict[str, tuple[str, str]]] = {
    "whatsapp": ("warn", "block"),
    "sms": ("warn", "warn"),
    "email": ("warn", "warn"),
    "messenger": ("warn", "warn"),
    "instagram": ("warn", "warn"),
    "call": ("show", "show"),
    "in_person": ("show", "show"),
    "other": ("show", "show"),
}
DEFAULT_HOURS: Final = (tuple(range(6)), time(10), time(20))  # Mon-Sat, 10:00-20:00
REPLY_WINDOW: Final = timedelta(hours=24)
WEEK: Final = timedelta(days=7)
RESERVATION: Final = timedelta(minutes=15)
OVERRIDE_FOR: Final = timedelta(minutes=30)
# A reply answers the newest unanswered touch on its channel this far back.
LINK_BACK: Final = timedelta(days=7)
# The newest touches read for one lead's guard (the cool-off streak reads "ever").
FACT_ROWS: Final = 500
NEVER_LEAD_MAX: Final = 200
PAGE: Final = 50
STATUS_ORDER: Final[dict[str, int]] = {
    "queued": 0,
    "opened": 1,
    "sent": 2,
    "delivered": 3,
    "read": 4,
}
NOT_LIVE: Final = ("failed", "expired")
# Sales X-Ray's own automations, as the timeline names them.
AUTOMATION_WORDS: Final[dict[str, str]] = {
    "first_reply": "First reply",
    "out_of_hours": "After-hours reply",
    "ai_reply": "AI reply",
    "drip": "Sequence",
    "broadcast": "Broadcast",
    "comment_reply": "Comment reply",
}
OVERRIDE_WORDS: Final[dict[str, str]] = {
    "lead_asked": "lead asked for it",
    "time_sensitive": "time-sensitive",
    "wrong_count": "the count was wrong",
    "other": "other",
}
# The lead event marker for a STOP on a channel other than WhatsApp (WhatsApp keeps its own,
# whatsapp/inbox.OPT_IN, so its campaigns and first replies honour a STOP said anywhere).
OPT_OUT: Final = "outreach_opt_out"
WHATSAPP_OPT_IN: Final = "whatsapp_opt_in"
EVENT_KIND: Final[dict[str, str]] = {"email": "email", "call": "call"}

Sender = Literal["person", "automation"]
Level = Literal["show", "warn", "block"]


# ----- settings ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Window:
    """The sending hours, in the workspace's time zone."""

    days: tuple[int, ...]  # 0 is Monday
    start: time
    end: time

    def inside(self, local: datetime) -> bool:
        return local.weekday() in self.days and self.start <= local.time() < self.end

    def next_open(self, after: datetime, tz: ZoneInfo = IST) -> datetime | None:
        """The first moment at or after ``after`` inside the hours (UTC)."""
        local = after.astimezone(tz)
        for step in range(15):
            day = local.date() + timedelta(days=step)
            if day.weekday() not in self.days:
                continue
            begins = datetime.combine(day, self.start, tzinfo=tz)
            ends = datetime.combine(day, self.end, tzinfo=tz)
            if begins <= local < ends:
                return after.astimezone(UTC)
            if begins >= local:
                return begins.astimezone(UTC)
        return None

    def view(self) -> SendHours:
        return SendHours(
            days=self.days, start=self.start.strftime("%H:%M"), end=self.end.strftime("%H:%M")
        )


@dataclass(frozen=True, slots=True)
class Rules:
    enabled: bool = True
    per_day: int = 1
    per_week: int = 3
    rest_after: int = 3
    rest_days: int = 14
    quiet: Window | None = None
    modes: Mapping[str, tuple[str, str]] = field(default_factory=lambda: dict(DEFAULT_MODES))
    keep_reply_words: bool = False
    never_lead: tuple[str, ...] = ()
    # Whether an owner or manager saved the limits: Sales X-Ray's own campaigns are held by
    # them only from then (the rollout's "show only" start, spec §10); a STOP always holds.
    saved: bool = False


def _int(raw: Any, default: int, low: int, high: int) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        return default
    return min(high, max(low, raw))


def _window(raw: Any) -> Window | None:
    if not isinstance(raw, Mapping):
        return None
    try:
        start, end = (
            time.fromisoformat(str(raw.get("start"))),
            time.fromisoformat(str(raw.get("end"))),
        )
    except ValueError:
        return None
    days = tuple(sorted({d for d in raw.get("days") or () if isinstance(d, int) and 0 <= d <= 6}))
    if not days or start >= end:
        return None
    return Window(days, start, end)


def _mode(raw: Any, default: str) -> str:
    return raw if isinstance(raw, str) and raw in MODES else default


def parse_rules(config: Mapping[str, Any]) -> Rules:
    """The workspace's outreach limits, the defaults for anything not set (spec §4.3)."""
    raw = config.get(KEY)
    raw = raw if isinstance(raw, Mapping) else {}
    modes: dict[str, tuple[str, str]] = {}
    given: Mapping[str, Any] = raw["modes"] if isinstance(raw.get("modes"), Mapping) else {}
    for channel, (people, automations) in DEFAULT_MODES.items():
        value = given.get(channel)
        if isinstance(value, Mapping):
            modes[channel] = (
                _mode(value.get("people"), people),
                _mode(value.get("automations"), automations),
            )
        elif isinstance(value, str) and value in MODES:
            modes[channel] = (value, value)
        else:
            modes[channel] = (people, automations)
    never = tuple(str(item) for item in raw.get("never_lead") or () if isinstance(item, str))
    return Rules(
        enabled=raw.get("enabled", True) is not False,
        per_day=_int(raw.get("per_day"), 1, 1, 10),
        per_week=_int(raw.get("per_week"), 3, 1, 30),
        rest_after=_int(raw.get("rest_after"), 3, 0, 20),
        rest_days=_int(raw.get("rest_days"), 14, 1, 90),
        quiet=_window(raw.get("quiet")),
        modes=modes,
        keep_reply_words=raw.get("keep_reply_words") is True,
        never_lead=never[:NEVER_LEAD_MAX],
        saved=isinstance(config.get(KEY), Mapping),
    )


def window_for(rules: Rules, config: Mapping[str, Any]) -> Window:
    """The sending hours in use: the outreach hours set, else the work hours, else 10-20."""
    if rules.quiet is not None:
        return rules.quiet
    hours = work_hours.parse(config)
    if hours is not None:
        return Window(hours.days, hours.start, hours.end)
    return Window(*DEFAULT_HOURS)


def mode_for(rules: Rules, channel: str, sender: Sender) -> str:
    people, automations = rules.modes.get(channel, ("show", "show"))
    return automations if sender == "automation" else people


def counts_on(channel: str, mode: str) -> bool:
    """Whether a touch on this channel counts toward the limits, in this mode."""
    if mode == "off":
        return False
    return mode in ("warn", "block") if channel in SHOWN_ONLY else True


def _clean_never(values: Iterable[str], country: str) -> tuple[str, ...]:
    out: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        found = first_email(text) if "@" in text else normalise_phone(text, default_country=country)
        if found is None:
            raise DeskError(422, "Never a lead takes phone numbers and emails only.")
        if found not in out:
            out.append(found)
    if len(out) > NEVER_LEAD_MAX:
        raise DeskError(422, f"Up to {NEVER_LEAD_MAX} phones and emails on Never a lead.")
    return tuple(out)


async def _settings(db: AsyncSession, tenant_id: UUID) -> tuple[int, dict[str, Any]]:
    row = await db.get(LeadDeskSettings, tenant_id)
    if row is None:
        return 0, {}
    return row.revision, dict(row.config or {})


def _rules_view(
    revision: int, rules: Rules, config: Mapping[str, Any], can_edit: bool
) -> OutreachRules:
    return OutreachRules(
        revision=revision,
        enabled=rules.enabled,
        per_day=rules.per_day,
        per_week=rules.per_week,
        rest_after=rules.rest_after,
        rest_days=rules.rest_days,
        quiet=rules.quiet.view() if rules.quiet else None,
        hours_in_use=window_for(rules, config).view(),
        modes={
            channel: OutreachChannelMode(people=people, automations=automations)
            for channel, (people, automations) in rules.modes.items()
        },
        keep_reply_words=rules.keep_reply_words,
        never_lead=rules.never_lead,
        can_edit=can_edit,
    )


async def rules_view(desk: LeadDesk) -> OutreachRules:
    """Lead rules › Outreach limits: everyone reads them; managers change them."""
    revision, config = await _settings(desk.db, desk.tenant_id)
    return _rules_view(revision, parse_rules(config), config, desk.viewer.can_manage)


async def save_rules(desk: LeadDesk, command: OutreachRulesCommand) -> OutreachRules:
    if not desk.viewer.can_manage:
        raise DeskError(403, "Owners, admins and managers set the outreach limits.")
    row = await desk.db.get(LeadDeskSettings, desk.tenant_id, with_for_update=True)
    current = row.revision if row else 0
    if current != command.expected_revision:
        raise DeskError(409, "Someone changed these settings. Reload and try again.")
    config = dict(row.config or {}) if row else {}
    saved = dict(config.get(KEY) or {}) if isinstance(config.get(KEY), Mapping) else {}
    changed: list[str] = []
    for name in ("enabled", "per_day", "per_week", "rest_after", "rest_days", "keep_reply_words"):
        value = getattr(command, name)
        if value is not None and saved.get(name) != value:
            saved[name] = value
            changed.append(name)
    if "quiet" in command.model_fields_set:
        quiet = (
            {
                "days": list(command.quiet.days),
                "start": command.quiet.start,
                "end": command.quiet.end,
            }
            if command.quiet is not None
            else None
        )
        if quiet is not None and _window(quiet) is None:
            raise DeskError(422, "Pick the days and an end after the start.")
        if saved.get("quiet") != quiet:
            saved["quiet"] = quiet
            changed.append("quiet")
    if command.modes is not None:
        modes = dict(saved.get("modes") or {})
        for channel, value in command.modes.items():
            people, automations = (
                (value, value)
                if isinstance(value, str)
                else (
                    value.people,
                    value.automations,
                )
            )
            modes[channel] = {"people": people, "automations": automations}
        if saved.get("modes") != modes:
            saved["modes"] = modes
            changed.append("modes")
    if command.never_lead is not None:
        country = str(config.get("default_country") or "91")
        never = list(_clean_never(command.never_lead, country))
        if saved.get("never_lead") != never:
            saved["never_lead"] = never
            changed.append("never_lead")
    if changed:
        config[KEY] = saved
        if row is None:
            row = LeadDeskSettings(tenant_id=desk.tenant_id, revision=0, config={})
            desk.db.add(row)
        row.revision = current + 1
        row.config = config
        row.updated_by_person_id = desk.viewer.person_id
        row.updated_at = desk.now
        await desk.db.flush()
        await _audit(
            desk.db,
            desk.tenant_id,
            action="lead_desk.outreach.settings_changed",
            resource_id=str(desk.tenant_id),
            payload={"fields": sorted(changed), "revision": row.revision},
            actor=desk.viewer.person_id,
            session_id=desk.viewer.session_id,
            now=desk.now,
        )
    return await rules_view(desk)


# ----- the guard (pure) ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Fact:
    """One touch as the guard reads it."""

    sent_at: datetime
    channel: str
    counted: bool
    status: str


@dataclass(frozen=True, slots=True)
class Facts:
    """What the guard knows about one lead (``facts`` reads it)."""

    lead_id: UUID | None = None
    touches: tuple[Fact, ...] = ()  # live ones: not failed, expired or a lapsed reservation
    last_inbound: Mapping[str, datetime] = field(default_factory=dict)
    opted_out: frozenset[str] = frozenset()
    state: Literal["live", "archived", "history", "bin", "test"] = "live"
    override_id: UUID | None = None
    internal: bool = False


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def _day_words(at: datetime, tz: ZoneInfo) -> str:
    return at.astimezone(tz).strftime("%a %-d %b")


def counter_words(
    last_touch_at: datetime | None, week: int, calls: int, now: datetime, tz: ZoneInfo = IST
) -> str:
    """The counter line, the same words everywhere a send starts (spec §4.2)."""
    if last_touch_at is None:
        return "Not contacted yet"
    local, today = last_touch_at.astimezone(tz), now.astimezone(tz).date()
    days = (today - local.date()).days
    if days <= 0:
        first = f"Touched today at {local.strftime('%H:%M')}"
    elif days == 1:
        first = "Last touched yesterday"
    elif days < 60:
        first = f"Last touched {days} days ago"
    else:
        first = f"Last touched on {local.strftime('%-d %b %Y')}"
    parts = [first, f"{_plural(week, 'touch', 'touches')} this week"]
    if calls:
        parts.append(_plural(calls, "call", "calls"))
    return " · ".join(parts)


def guard(
    facts: Facts,
    *,
    channel: str,
    sender: Sender,
    rules: Rules,
    window: Window,
    now: datetime,
    tz: ZoneInfo = IST,
) -> OutreachGuard:
    """ok, warn or block for one more touch to this lead on this channel (spec §4.1)."""
    mode = mode_for(rules, channel, sender)
    limit: Level = (
        ("warn" if mode == "warn" else "block" if mode == "block" else "show")
        if rules.enabled
        else "show"
    )
    reasons: list[tuple[str, str, Level, datetime | None]] = []
    live = [fact for fact in facts.touches if fact.status not in NOT_LIVE]
    sent = [fact for fact in live if fact.status != "queued"]
    counted = sorted((fact for fact in live if fact.counted), key=lambda fact: fact.sent_at)
    local_now = now.astimezone(tz)
    day_start = datetime.combine(local_now.date(), time.min, tzinfo=tz).astimezone(UTC)
    today = sum(1 for fact in counted if fact.sent_at >= day_start)
    week = [fact.sent_at for fact in counted if fact.sent_at > now - WEEK]
    last_in = max(facts.last_inbound.values(), default=None)
    streak = [fact for fact in counted if last_in is None or fact.sent_at > last_in]
    calls_week = sum(1 for fact in sent if fact.channel == "call" and fact.sent_at > now - WEEK)
    last_touch_at = max((fact.sent_at for fact in sent), default=None)
    opted = channel in facts.opted_out

    # 1. A STOP on this channel: nothing overrides it.
    if opted:
        reasons.append(("opted_out", f"Said stop on {CHANNEL_WORDS[channel]}", "block", None))
    for other in sorted(facts.opted_out - {channel}):
        reasons.append(("opted_out_other", f"Said stop on {CHANNEL_WORDS[other]}", "show", None))
    # 2. Where the lead is.
    if facts.state == "bin":
        reasons.append(("in_bin", "In the Bin", "block", None))
    elif facts.state == "test":
        # Sandbox practice leads are test data: a person in the app is told, never stopped.
        reasons.append(
            ("test_data", "Test data", "block" if sender == "automation" else "warn", None)
        )
    elif facts.state in ("archived", "history") and rules.enabled:
        words = "Archived lead" if facts.state == "archived" else "Kept as history"
        reasons.append((facts.state, words, "warn", None))
    if facts.internal:
        reasons.append(("internal", "On the team's Never a lead list", "show", None))
    # 3. The lead wrote in the last 24 hours on this channel: a conversation, never spam.
    inbound = facts.last_inbound.get(channel)
    in_window = inbound is not None and now - inbound < REPLY_WINDOW
    if not in_window and counts_on(channel, mode):
        # 4. The day limit, in the workspace's day.
        if today >= rules.per_day:
            tomorrow = day_start + timedelta(days=1)
            reasons.append(
                (
                    "day_cap",
                    "Touched today already"
                    if rules.per_day == 1
                    else f"{_plural(today, 'touch', 'touches')} today",
                    limit,
                    window.next_open(tomorrow, tz) or tomorrow,
                )
            )
        # 5. The week limit, a rolling 7 days.
        if len(week) >= rules.per_week:
            frees = week[len(week) - rules.per_week] + WEEK
            reasons.append(
                (
                    "week_cap",
                    f"{_plural(len(week), 'touch', 'touches')} in the last 7 days",
                    limit,
                    frees,
                )
            )
        # 6. The cool-off: that many unanswered in a row, then the lead rests.
        if rules.rest_after and len(streak) >= rules.rest_after:
            rests = streak[-1].sent_at + timedelta(days=rules.rest_days)
            if rests > now:
                reasons.append(
                    (
                        "rest",
                        f"{_plural(len(streak), 'touch', 'touches')} with no answer: rests until"
                        f" {_day_words(rests, tz)}",
                        limit,
                        rests,
                    )
                )
    quiet_until: datetime | None = None
    if (
        not in_window
        and rules.enabled
        and mode in ("warn", "block")
        and not window.inside(local_now)
    ):
        # 7. Outside the sending hours: people are told, automations wait.
        quiet_until = window.next_open(now, tz)
        reasons.append(
            (
                "quiet",
                f"Outside sending hours ({window.start.strftime('%H:%M')}"
                f"-{window.end.strftime('%H:%M')})",
                "block" if sender == "automation" else "warn",
                quiet_until,
            )
        )
    severity = {"show": 0, "warn": 1, "block": 2}
    top = max((severity[level] for _, _, level, _ in reasons), default=0)
    verdict: Literal["ok", "warn", "block"] = ("ok", "warn", "block")[top]
    override_id: UUID | None = None
    # 8. A manager's "send anyway", never past a STOP.
    if verdict != "ok" and facts.override_id is not None and not opted:
        verdict, override_id = "ok", facts.override_id
    waits = [
        at
        for _, _, level, at in reasons
        if at is not None and level in ("warn", "block") and verdict != "ok"
    ]
    return OutreachGuard(
        lead_id=facts.lead_id,
        channel=channel,
        mode=mode,
        verdict=verdict,
        reasons=tuple(
            OutreachReason(code=code, words=words, level=level) for code, words, level, _ in reasons
        ),
        words=counter_words(last_touch_at, len(week), calls_week, now, tz),
        last_touch_at=last_touch_at,
        counts=OutreachCounts(
            today=today, week=len(week), unanswered=len(streak), calls_week=calls_week
        ),
        next_ok_at=None if opted or not waits else max(waits),
        quiet_until=quiet_until,
        opted_out=opted,
        in_reply_window=in_window,
        override=OverrideHint(
            possible=verdict != "ok" and not opted and sender == "person" and facts.state != "bin"
        ),
        override_id=override_id,
    )


def would_count(result: OutreachGuard, *, internal: bool = False) -> bool:
    """Whether one more touch, sent now, counts toward the limits."""
    return not result.in_reply_window and not internal and counts_on(result.channel, result.mode)


# ----- reads --------------------------------------------------------------------------------


def _state(lead: Lead) -> Literal["live", "archived", "history", "bin", "test"]:
    if lead.binned_at is not None:
        return "bin"
    if lead.test_data:
        return "test"
    if lead.archived_at is not None:
        return "archived"
    if lead.pipeline == HISTORY:
        return "history"
    return "live"


async def opt_outs(db: AsyncSession, tenant_id: UUID, lead_id: UUID) -> frozenset[str]:
    """The channels this lead said STOP on: its newest word per channel stands."""
    rows = (
        await db.scalars(
            select(LeadEvent.data)
            .where(
                LeadEvent.tenant_id == tenant_id,
                LeadEvent.lead_id == lead_id,
                LeadEvent.kind == "edited",
            )
            .order_by(LeadEvent.created_at.desc())
            .limit(2000)
        )
    ).all()
    decided: dict[str, bool] = {}
    for data in rows:
        if not isinstance(data, Mapping):
            continue
        if isinstance(data.get(WHATSAPP_OPT_IN), bool) and "whatsapp" not in decided:
            decided["whatsapp"] = data[WHATSAPP_OPT_IN] is False
        channel = data.get(OPT_OUT)
        if isinstance(channel, str) and channel in CHANNELS and channel not in decided:
            decided[channel] = data.get("said", True) is not False
    return frozenset(channel for channel, said in decided.items() if said)


async def last_inbound(db: AsyncSession, tenant_id: UUID, lead_id: UUID) -> dict[str, datetime]:
    """When the lead last wrote to us, per channel (Sales X-Ray's own chats and the replies
    outside senders reported)."""
    found: dict[str, datetime] = {}

    def keep(channel: str, at: datetime | None) -> None:
        if at is not None and (channel not in found or at > found[channel]):
            found[channel] = at

    keep(
        "whatsapp",
        await db.scalar(
            select(
                func.max(
                    func.coalesce(LeadWhatsAppMessage.meta_time, LeadWhatsAppMessage.created_at)
                )
            ).where(
                LeadWhatsAppMessage.tenant_id == tenant_id,
                LeadWhatsAppMessage.lead_id == lead_id,
                LeadWhatsAppMessage.direction == "in",
            )
        ),
    )
    for channel, at in (
        await db.execute(
            select(
                LeadSocialMessage.channel,
                func.max(func.coalesce(LeadSocialMessage.meta_time, LeadSocialMessage.created_at)),
            )
            .where(
                LeadSocialMessage.tenant_id == tenant_id,
                LeadSocialMessage.lead_id == lead_id,
                LeadSocialMessage.direction == "in",
            )
            .group_by(LeadSocialMessage.channel)
        )
    ).all():
        keep(str(channel), at)
    for channel, at in (
        await db.execute(
            select(LeadTouchReply.channel, func.max(LeadTouchReply.received_at))
            .where(LeadTouchReply.tenant_id == tenant_id, LeadTouchReply.lead_id == lead_id)
            .group_by(LeadTouchReply.channel)
        )
    ).all():
        keep(str(channel), at)
    return found


async def _members_contact(db: AsyncSession, tenant_id: UUID, country: str) -> set[str]:
    rows = (
        await db.execute(
            select(Person.email, Person.whatsapp_number)
            .join(Membership, Membership.person_id == Person.id)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.status == "active",
                Membership.ended_at.is_(None),
            )
        )
    ).all()
    found: set[str] = set()
    for email, phone in rows:
        if email:
            found.add(str(email).strip().lower())
        number = normalise_phone(phone, default_country=country) if phone else None
        if number:
            found.add(number)
    return found


async def internal(
    db: AsyncSession,
    tenant_id: UUID,
    rules: Rules,
    config: Mapping[str, Any],
    *,
    phone: str | None,
    email: str | None,
) -> bool:
    """A teammate or a contact on the Never a lead list: never a lead, never counted."""
    wanted = {value for value in (phone, (email or "").strip().lower() or None) if value}
    if not wanted:
        return False
    if wanted & set(rules.never_lead):
        return True
    country = str(config.get("default_country") or "91")
    return bool(wanted & await _members_contact(db, tenant_id, country))


async def facts(
    db: AsyncSession,
    tenant_id: UUID,
    lead: Lead,
    channel: str,
    now: datetime,
    *,
    rules: Rules | None = None,
    config: Mapping[str, Any] | None = None,
) -> Facts:
    rows = (
        await db.execute(
            select(LeadTouch.sent_at, LeadTouch.channel, LeadTouch.counted, LeadTouch.status)
            .where(
                LeadTouch.tenant_id == tenant_id,
                LeadTouch.lead_id == lead.id,
                LeadTouch.status.not_in(NOT_LIVE),
                or_(LeadTouch.status != "queued", LeadTouch.expires_at > now),
            )
            .order_by(LeadTouch.sent_at.desc())
            .limit(FACT_ROWS)
        )
    ).all()
    override = await db.scalar(
        select(LeadTouchOverride.id)
        .where(
            LeadTouchOverride.tenant_id == tenant_id,
            LeadTouchOverride.lead_id == lead.id,
            LeadTouchOverride.channel == channel,
            LeadTouchOverride.used_at.is_(None),
            LeadTouchOverride.expires_at > now,
        )
        .order_by(LeadTouchOverride.created_at.desc())
        .limit(1)
    )
    is_internal = False
    if rules is not None and config is not None:
        is_internal = await internal(
            db, tenant_id, rules, config, phone=lead.phone, email=lead.email
        )
    return Facts(
        lead_id=lead.id,
        touches=tuple(Fact(row[0], row[1], row[2], row[3]) for row in rows),
        last_inbound=await last_inbound(db, tenant_id, lead.id),
        opted_out=await opt_outs(db, tenant_id, lead.id),
        state=_state(lead),
        override_id=override,
        internal=is_internal,
    )


async def check_lead(
    db: AsyncSession,
    tenant_id: UUID,
    lead: Lead,
    channel: str,
    sender: Sender,
    now: datetime,
) -> tuple[OutreachGuard, Rules, Facts]:
    """The guard for one lead and channel, read from the database."""
    _, config = await _settings(db, tenant_id)
    rules = parse_rules(config)
    found = await facts(db, tenant_id, lead, channel, now, rules=rules, config=config)
    result = guard(
        found,
        channel=channel,
        sender=sender,
        rules=rules,
        window=window_for(rules, config),
        now=now,
    )
    return result, rules, found


def main_channel(lead: Lead) -> str:
    return "whatsapp" if lead.phone else "email" if lead.email else "whatsapp"


async def for_lead(desk: LeadDesk, lead: Lead, channel: str | None = None) -> OutreachGuard:
    result, _, _ = await check_lead(
        desk.db, desk.tenant_id, lead, channel or main_channel(lead), "person", desk.now
    )
    return result


async def lead_outreach(desk: LeadDesk, lead_id: UUID, channel: str | None) -> OutreachGuard:
    """GET /leads/{id}/outreach: the counter and guard for one channel."""
    if channel is not None and channel not in CHANNELS:
        raise DeskError(422, "Pick a channel.")
    lead, _ = await desk._readable(lead_id)
    return await for_lead(desk, lead, channel)


async def bulk(desk: LeadDesk, command: BulkGuardCommand) -> BulkGuard:
    """POST /outreach/guard: counts for up to 500 leads (bulk WhatsApp, a campaign's audience)."""
    if not desk.viewer.can_manage:
        raise DeskError(403, "Owners, admins and managers check many leads at once.")
    leads = (
        await desk.db.scalars(
            select(Lead).where(desk._visible(), Lead.id.in_(list(dict.fromkeys(command.lead_ids))))
        )
    ).all()
    _, config = await _settings(desk.db, desk.tenant_id)
    rules = parse_rules(config)
    window = window_for(rules, config)
    rows: list[BulkGuardLead] = []
    for lead in leads:
        found = await facts(desk.db, desk.tenant_id, lead, command.channel, desk.now)
        result = guard(
            found,
            channel=command.channel,
            sender=command.sender,
            rules=rules,
            window=window,
            now=desk.now,
        )
        rows.append(
            BulkGuardLead(
                lead_id=lead.id,
                verdict=result.verdict,
                opted_out=result.opted_out,
                words=result.words,
                next_ok_at=result.next_ok_at,
            )
        )
    ok = sum(1 for row in rows if row.verdict == "ok")
    warned = sum(1 for row in rows if row.verdict == "warn")
    held = sum(1 for row in rows if row.verdict == "block")
    stop = sum(1 for row in rows if row.opted_out)
    words = f"{ok} ok · {warned} warned · {held} held"
    if stop:
        words += f" ({stop} said stop)"
    return BulkGuard(
        channel=command.channel,
        ok=ok,
        warned=warned,
        held=held,
        said_stop=stop,
        words=words,
        leads=tuple(rows),
    )


# ----- writes -------------------------------------------------------------------------------


async def _audit(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    action: str,
    resource_id: str,
    payload: dict[str, Any],
    actor: UUID | None,
    now: datetime,
    session_id: UUID | None = None,
    actor_type: str = "person",
) -> None:
    await AuditRepository(db).append(
        tenant_id=tenant_id,
        actor_person_id=actor,
        actor_type=actor_type if actor is not None or actor_type != "person" else "system",
        session_id=session_id,
        action=action,
        resource_type=AUDIT_RESOURCE,
        resource_id=resource_id,
        payload=payload,
        now=now,
    )


def guard_record(
    result: OutreachGuard, *, counts: bool, after_block: bool = False
) -> dict[str, Any]:
    """What a touch keeps of the guard's verdict when it went."""
    record: dict[str, Any] = {
        "verdict": result.verdict,
        "reasons": [reason.code for reason in result.reasons if reason.level != "show"],
        "mode": result.mode,
        "counts": counts,
    }
    if result.override_id is not None:
        record["override_id"] = str(result.override_id)
    if after_block:
        record["after_block"] = True
    return record


def _summary(text: str | None) -> str | None:
    words = " ".join((text or "").split())
    return words[:280] or None


def _event_for(
    desk: LeadDesk,
    lead: Lead,
    channel: str,
    *,
    actor: UUID | None,
    data: dict[str, Any],
    at: datetime,
    command_id: UUID | None = None,
) -> LeadEvent:
    return desk._event(
        lead,
        EVENT_KIND.get(channel, "message"),
        {"channel": channel, **data},
        actor=actor,
        command_id=command_id,
        at=at,
    )


async def record_touch(
    desk: LeadDesk,
    lead: Lead,
    *,
    channel: str,
    content_kind: str,
    via: str,
    sender_type: Sender,
    person_id: UUID | None = None,
    sender: LeadOutreachSender | None = None,
    automation: str | None = None,
    provider: str | None = None,
    provider_message_id: str | None = None,
    provider_chat_id: str | None = None,
    client_ref: str | None = None,
    summary: str | None = None,
    template_name: str | None = None,
    attachment: dict[str, Any] | None = None,
    status: str = "sent",
    sent_at: datetime | None = None,
    event: LeadEvent | None = None,
    event_data: dict[str, Any] | None = None,
    whatsapp_message_id: UUID | None = None,
    social_message_id: UUID | None = None,
    campaign_id: UUID | None = None,
    command_id: UUID | None = None,
    request_sha256: str | None = None,
    error_code: str | None = None,
    result: OutreachGuard | None = None,
    reserve: bool = False,
) -> LeadTouch:
    """Store one touch (and its timeline line, unless ``event`` is the line already made).

    The guard is read first (or ``result`` is the one the send already asked); its verdict is
    kept on the touch. A touch the guard would have blocked, from an outside sender, is still
    stored, counted, flagged ``after_block`` and audited (``sent_past_block``). A manager's
    override the guard used is used up by this touch. ``reserve`` keeps a 15-minute
    reservation instead (``status`` queued, no timeline line yet)."""
    at = min(sent_at or desk.now, desk.now)
    _, config = await _settings(desk.db, desk.tenant_id)
    rules = parse_rules(config)
    if result is None:
        found = await facts(
            desk.db, desk.tenant_id, lead, channel, desk.now, rules=rules, config=config
        )
        result = guard(
            found,
            channel=channel,
            sender=sender_type,
            rules=rules,
            window=window_for(rules, config),
            now=desk.now,
        )
        is_internal = found.internal
    else:
        is_internal = await internal(
            desk.db, desk.tenant_id, rules, config, phone=lead.phone, email=lead.email
        )
    counts = would_count(result, internal=is_internal)
    after_block = sender is not None and result.verdict == "block" and not reserve
    touch = LeadTouch(
        id=uuid4(),
        tenant_id=desk.tenant_id,
        lead_id=lead.id,
        channel=channel,
        content_kind=content_kind,
        initiated="reply" if result.in_reply_window else "outreach",
        sender_type=sender_type,
        person_id=person_id if sender_type == "person" else None,
        sender_id=sender.id if sender is not None else None,
        automation=automation,
        campaign_id=campaign_id,
        via=via,
        provider=provider,
        provider_message_id=provider_message_id,
        provider_chat_id=provider_chat_id,
        client_ref=client_ref,
        summary=_summary(summary),
        template_name=template_name,
        attachment=attachment,
        status="queued" if reserve else status,
        status_at=at if status not in ("queued", "opened") and not reserve else None,
        error_code=error_code,
        sent_at=at,
        expires_at=desk.now + RESERVATION if reserve else None,
        counted=counts and (reserve or status not in NOT_LIVE),
        guard=guard_record(result, counts=counts, after_block=after_block),
        override_id=result.override_id,
        event_id=None,
        whatsapp_message_id=whatsapp_message_id,
        social_message_id=social_message_id,
        request_sha256=request_sha256,
        command_id=command_id,
        created_at=desk.now,
        updated_at=desk.now,
    )
    if not reserve:
        line = event or _event_for(
            desk,
            lead,
            channel,
            actor=person_id if sender_type == "person" else None,
            data={"via": via, "touch_id": str(touch.id), **(event_data or {})},
            at=at,
        )
        touch.event_id = line.id
    desk.db.add(touch)
    await desk.db.flush()
    await _after_write(desk, lead, touch, result, sender=sender)
    return touch


async def _after_write(
    desk: LeadDesk,
    lead: Lead,
    touch: LeadTouch,
    result: OutreachGuard,
    *,
    sender: LeadOutreachSender | None,
) -> None:
    if touch.status == "queued":
        return
    if result.override_id is not None:
        override = await desk.db.scalar(
            select(LeadTouchOverride)
            .where(
                LeadTouchOverride.tenant_id == desk.tenant_id,
                LeadTouchOverride.id == result.override_id,
                LeadTouchOverride.used_at.is_(None),
            )
            .with_for_update()
        )
        if override is not None:
            override.used_by_touch_id, override.used_at = touch.id, desk.now
            await desk.db.flush()
            await _audit(
                desk.db,
                desk.tenant_id,
                action="lead_desk.outreach.override_used",
                resource_id=str(override.id),
                payload={"touch_id": str(touch.id), "lead_id": str(lead.id)},
                actor=touch.person_id or override.granted_by_person_id,
                now=desk.now,
            )
    if touch.guard.get("after_block") and sender is not None:
        await _audit(
            desk.db,
            desk.tenant_id,
            action="lead_desk.outreach.sent_past_block",
            resource_id=str(touch.id),
            payload={
                "lead_id": str(lead.id),
                "sender_id": str(sender.id),
                "channel": touch.channel,
                "reasons": list(touch.guard.get("reasons") or []),
            },
            actor=sender.person_id or sender.created_by_person_id,
            actor_type="api_key",
            now=desk.now,
        )
    if touch.sender_type == "person" and touch.status not in NOT_LIVE:
        # A person's touch is contact (reassign_guard), as an in-app WhatsApp is.
        lead.first_contact_at = lead.first_contact_at or touch.sent_at
    lead.updated_at = desk.now


async def mirror(
    desk: LeadDesk,
    lead: Lead,
    event: LeadEvent,
    *,
    channel: str,
    content_kind: str,
    via: str,
    person_id: UUID | None,
    automation: str | None = None,
    provider: str | None = None,
    status: str = "sent",
    whatsapp_message_id: UUID | None = None,
    template_name: str | None = None,
    attachment: dict[str, Any] | None = None,
    campaign_id: UUID | None = None,
    command_id: UUID | None = None,
    result: OutreachGuard | None = None,
    error_code: str | None = None,
) -> LeadTouch:
    """The touch for a timeline line Sales X-Ray itself just wrote (a ready message opened, a
    Cloud API send, a call); never a second one for the same line."""
    existing = await desk.db.scalar(
        select(LeadTouch).where(
            LeadTouch.tenant_id == desk.tenant_id, LeadTouch.event_id == event.id
        )
    )
    if existing is not None:
        return existing
    return await record_touch(
        desk,
        lead,
        channel=channel,
        content_kind=content_kind,
        via=via,
        sender_type="person" if person_id is not None else "automation",
        person_id=person_id,
        automation=automation,
        provider=provider,
        status=status,
        sent_at=event.created_at,
        event=event,
        whatsapp_message_id=whatsapp_message_id,
        template_name=template_name,
        attachment=attachment,
        campaign_id=campaign_id,
        command_id=command_id,
        result=result,
        error_code=error_code,
    )


async def enforce(desk: LeadDesk, lead: Lead, channel: str, sender: Sender) -> OutreachGuard:
    """An in-app send asks first (v1.95.1): a block refuses it (409), with the reason and what a
    manager can do; an automation also waits on a warning. Returns the verdict to keep."""
    result, _, _ = await check_lead(desk.db, desk.tenant_id, lead, channel, sender, desk.now)
    if result.verdict == "block" or (sender == "automation" and result.verdict == "warn"):
        reason = next(
            (r.words for r in result.reasons if r.level == result.verdict), "Outreach limit"
        )
        hint = " A manager can send anyway." if result.override.possible else ""
        raise DeskError(409, f"Held by the outreach limits: {reason}.{hint}")
    return result


def advance(current: str, current_at: datetime | None, new: str, at: datetime) -> bool:
    """Statuses move forward only; a failed send stays failed unless a later delivery
    arrives (a Meta retry that worked); an update older than the last one is ignored."""
    if new == current:
        return False
    if current_at is not None and at < current_at:
        return False
    if current in ("expired",):
        return False
    if current == "failed":
        return new in ("delivered", "read")
    if new == "failed":
        return True
    return STATUS_ORDER.get(new, -1) > STATUS_ORDER.get(current, -1)


def apply_status(
    touch: LeadTouch, status: str, at: datetime, error_code: str | None, now: datetime
) -> bool:
    if not advance(touch.status, touch.status_at, status, at):
        return False
    touch.status, touch.status_at, touch.updated_at = status, at, now
    if status == "failed":
        touch.error_code = (error_code or "failed")[:32]
    touch.counted = bool(touch.guard.get("counts")) and status not in NOT_LIVE
    return True


async def copy_whatsapp_status(
    db: AsyncSession, wamid: str, status: str, at: datetime, error_code: str | None, now: datetime
) -> int:
    """A Cloud API status for one of our sends reaches its touch (the webhook's transaction);
    a wamid Sales X-Ray never sent itself may be an outside sender's (sx-engage on the same
    number), logged as a meta_cloud touch."""
    copied = 0
    message_ids = select(LeadWhatsAppMessage.id).where(LeadWhatsAppMessage.wamid == wamid)
    rows = (
        await db.scalars(
            select(LeadTouch)
            .where(
                or_(
                    LeadTouch.whatsapp_message_id.in_(message_ids),
                    and_(
                        LeadTouch.provider == "meta_cloud",
                        LeadTouch.provider_message_id == wamid,
                    ),
                )
            )
            .with_for_update()
        )
    ).all()
    for touch in rows:
        copied += apply_status(touch, status, at, error_code, now)
    return copied


async def link_reply(
    db: AsyncSession,
    tenant_id: UUID,
    lead_id: UUID,
    channel: str,
    at: datetime,
    ref: dict[str, Any],
    *,
    in_reply_to: tuple[str | None, str | None, str] | None = None,
) -> LeadTouch | None:
    """An inbound message answers a touch: the one it names (provider, chat, id), else the
    newest unanswered touch on that lead and channel in the 7 days before it."""
    query = select(LeadTouch).where(
        LeadTouch.tenant_id == tenant_id,
        LeadTouch.lead_id == lead_id,
        LeadTouch.replied_at.is_(None),
        LeadTouch.status.not_in(("failed", "expired", "queued")),
    )
    touch: LeadTouch | None = None
    if in_reply_to is not None:
        provider, chat, message_id = in_reply_to
        touch = await db.scalar(
            query.where(
                LeadTouch.provider == provider,
                func.coalesce(LeadTouch.provider_chat_id, "") == (chat or ""),
                LeadTouch.provider_message_id == message_id,
            ).with_for_update()
        )
    if touch is None:
        touch = await db.scalar(
            query.where(
                LeadTouch.channel == channel,
                LeadTouch.sent_at <= at,
                LeadTouch.sent_at > at - LINK_BACK,
            )
            .order_by(LeadTouch.sent_at.desc())
            .limit(1)
            .with_for_update()
        )
    if touch is not None:
        touch.replied_at, touch.reply_ref = at, ref
    return touch


async def record_opt_out(desk: LeadDesk, lead: Lead, channel: str, how: str) -> bool:
    """A STOP on one channel: kept on the lead (an ``edited`` line), so every engine and every
    send button honours it. WhatsApp uses its own marker, which campaigns already read."""
    if channel in await opt_outs(desk.db, desk.tenant_id, lead.id):
        return False
    data: dict[str, Any] = (
        {WHATSAPP_OPT_IN: False, "how": how}
        if channel == "whatsapp"
        else {OPT_OUT: channel, "said": True, "how": how}
    )
    desk._event(lead, "edited", data, actor=None)
    await desk.db.flush()
    return True


async def expire_reservations(db: AsyncSession, now: datetime, *, limit: int = 1000) -> int:
    """Reservations nobody completed end by themselves (the minute loop): expired, uncounted."""
    ids = (
        await db.scalars(
            select(LeadTouch.id)
            .where(LeadTouch.status == "queued", LeadTouch.expires_at <= now)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()
    if not ids:
        return 0
    await db.execute(
        update(LeadTouch)
        .where(LeadTouch.id.in_(ids), LeadTouch.status == "queued")
        .values(status="expired", expires_at=None, counted=False, status_at=now, updated_at=now)
    )
    return len(ids)


# ----- the timeline and the touch list ----------------------------------------------------


async def views(desk: LeadDesk, touches: Sequence[LeadTouch]) -> list[TouchView]:
    if not touches:
        return []
    sender_ids = {touch.sender_id for touch in touches if touch.sender_id}
    labels: dict[UUID, str] = {}
    if sender_ids:
        labels = dict(
            (
                await desk.db.execute(
                    select(LeadOutreachSender.id, LeadOutreachSender.label).where(
                        LeadOutreachSender.tenant_id == desk.tenant_id,
                        LeadOutreachSender.id.in_(sender_ids),
                    )
                )
            )
            .tuples()
            .all()
        )
    override_ids = {touch.override_id for touch in touches if touch.override_id}
    overrides: dict[UUID, LeadTouchOverride] = {}
    if override_ids:
        overrides = {
            row.id: row
            for row in await desk.db.scalars(
                select(LeadTouchOverride).where(
                    LeadTouchOverride.tenant_id == desk.tenant_id,
                    LeadTouchOverride.id.in_(override_ids),
                )
            )
        }
    names = await desk._names(
        {touch.person_id for touch in touches}
        | {row.granted_by_person_id for row in overrides.values()}
    )
    out: list[TouchView] = []
    for touch in touches:
        label = labels.get(touch.sender_id) if touch.sender_id else None
        automation = (
            AUTOMATION_WORDS.get(touch.automation, touch.automation) if touch.automation else None
        )
        by = (
            names.get(touch.person_id, "Someone")
            if touch.person_id
            else label or automation or "Sales X-Ray"
        )
        granted = overrides.get(touch.override_id) if touch.override_id else None
        out.append(
            TouchView(
                touch_id=touch.id,
                lead_id=touch.lead_id,
                channel=touch.channel,
                content_kind=touch.content_kind,
                initiated=touch.initiated,
                sender_type=touch.sender_type,
                by_name=by,
                person_id=touch.person_id,
                sender_id=touch.sender_id,
                sender_label=label,
                automation=touch.automation,
                via=touch.via,
                provider=touch.provider,
                summary=touch.summary,
                template_name=touch.template_name,
                attachment=touch.attachment,
                status=touch.status,
                status_at=touch.status_at,
                sent_at=touch.sent_at,
                counted=touch.counted,
                verdict=str((touch.guard or {}).get("verdict") or "ok"),
                after_block=bool((touch.guard or {}).get("after_block")),
                override_by_name=names.get(granted.granted_by_person_id) if granted else None,
                override_reason=(
                    granted.reason_text
                    if granted and granted.reason_key == "other"
                    else OVERRIDE_WORDS.get(granted.reason_key)
                    if granted
                    else None
                ),
                replied_at=touch.replied_at,
                event_id=touch.event_id,
            )
        )
    return out


async def lines(desk: LeadDesk, events: Iterable[LeadEvent]) -> dict[UUID, TouchView]:
    """The timeline merge: each message, email or call line's touch, by the line's id."""
    ids = [event.id for event in events if event.kind in ("message", "email", "call")]
    if not ids:
        return {}
    touches = (
        await desk.db.scalars(
            select(LeadTouch).where(
                LeadTouch.tenant_id == desk.tenant_id, LeadTouch.event_id.in_(ids)
            )
        )
    ).all()
    return {view.event_id: view for view in await views(desk, touches) if view.event_id}


def _cursor(touch: LeadTouch) -> str:
    return f"{touch.sent_at.isoformat()}|{touch.id}"


def parse_cursor(cursor: str | None) -> tuple[datetime, UUID] | None:
    if not cursor:
        return None
    try:
        at, _, ident = cursor.partition("|")
        return datetime.fromisoformat(at), UUID(ident)
    except ValueError:
        raise DeskError(422, "That page link is wrong.") from None


async def page_for(
    desk: LeadDesk, lead_id: UUID, cursor: str | None, *, limit: int = PAGE
) -> TouchPage:
    """GET /leads/{id}/touches: the lead's touches, newest first (the touch sheet, "All
    touches for this lead"); reservations are not touches yet."""
    lead, _ = await desk._readable(lead_id)
    query = select(LeadTouch).where(
        LeadTouch.tenant_id == desk.tenant_id,
        LeadTouch.lead_id == lead.id,
        LeadTouch.status != "queued",
    )
    after = parse_cursor(cursor)
    if after is not None:
        query = query.where(
            or_(
                LeadTouch.sent_at < after[0],
                and_(LeadTouch.sent_at == after[0], LeadTouch.id < after[1]),
            )
        )
    rows = (
        await desk.db.scalars(
            query.order_by(LeadTouch.sent_at.desc(), LeadTouch.id.desc()).limit(limit + 1)
        )
    ).all()
    more = len(rows) > limit
    rows = rows[:limit]
    return TouchPage(
        touches=tuple(await views(desk, rows)),
        next_cursor=_cursor(rows[-1]) if more and rows else None,
    )


CONTENT_FOR: Final[dict[str, str]] = {"call": "call", "in_person": "file"}


async def log_touch(desk: LeadDesk, lead_id: UUID, command: TouchCommand) -> TouchLogged:
    """POST /leads/{id}/touches: "Log a touch" (a call from another phone, an email from Gmail,
    a PDF handed over in person) or a mailto/sms link the app opened; anyone who may change
    the lead. Its timeline line is made with it. The same command again is that touch."""
    seen = await desk.db.scalar(
        select(LeadTouch).where(
            LeadTouch.tenant_id == desk.tenant_id, LeadTouch.command_id == command.command_id
        )
    )
    if seen is not None:
        if seen.lead_id != lead_id:
            raise DeskError(409, "That request was already used for another lead.")
        lead = await desk._lead(lead_id)
        return TouchLogged(
            touch=(await views(desk, [seen]))[0], outreach=await for_lead(desk, lead, seen.channel)
        )
    lead = await desk._lead(lead_id, lock=True)
    if not (desk.viewer.can_manage or lead.owner_person_id == desk.viewer.person_id):
        raise DeskError(403, "Only the lead's owner or a manager can log a touch here.")
    if command.sent_at is not None and command.sent_at > desk.now + timedelta(minutes=5):
        raise DeskError(422, "That time is in the future.")
    result, _, _ = await check_lead(
        desk.db, desk.tenant_id, lead, command.channel, "person", desk.now
    )
    if result.opted_out:
        raise DeskError(409, f"They said stop on {CHANNEL_WORDS[command.channel]}.")
    content = command.content_kind or (
        "file" if command.attachment is not None else CONTENT_FOR.get(command.channel, "text")
    )
    touch = await record_touch(
        desk,
        lead,
        channel=command.channel,
        content_kind=content,
        via=command.via,
        sender_type="person",
        person_id=desk.viewer.person_id,
        summary=command.summary,
        attachment=command.attachment.model_dump() if command.attachment else None,
        status="opened" if command.via == "app_link" else "sent",
        sent_at=command.sent_at,
        command_id=command.command_id,
        event_data={"logged": True} if command.via == "manual" else None,
        result=result,
    )
    return TouchLogged(
        touch=(await views(desk, [touch]))[0],
        outreach=await for_lead(desk, lead, command.channel),
    )


# ----- manager overrides ----------------------------------------------------------------------


async def grant_override(desk: LeadDesk, lead_id: UUID, command: OverrideCommand) -> OverrideView:
    """POST /leads/{id}/overrides: an owner, admin or manager's one-time "send anyway" for this
    lead and channel, with the reason, for 30 minutes. Never past a STOP. Audited."""
    if not desk.viewer.can_manage:
        raise DeskError(403, "Owners, admins and managers can send anyway. Ask a manager.")
    if command.reason_key == "other" and not (command.reason_text or "").strip():
        raise DeskError(422, "Say why in a few words.")
    lead = await desk._lead(lead_id, lock=True)
    seen = await desk.db.scalar(
        select(LeadTouchOverride).where(
            LeadTouchOverride.tenant_id == desk.tenant_id,
            LeadTouchOverride.command_id == command.command_id,
        )
    )
    if seen is None:
        result, _, _ = await check_lead(
            desk.db, desk.tenant_id, lead, command.channel, "person", desk.now
        )
        if result.opted_out:
            raise DeskError(409, "They said stop: nobody can send anyway.")
        if result.verdict == "ok":
            raise DeskError(409, "Nothing is holding this send: just send it.")
        seen = LeadTouchOverride(
            id=uuid4(),
            tenant_id=desk.tenant_id,
            lead_id=lead.id,
            channel=command.channel,
            granted_by_person_id=desk.viewer.person_id,
            asked_by_person_id=None,
            reason_key=command.reason_key,
            reason_text=(command.reason_text or "").strip() or None,
            verdict={
                "verdict": result.verdict,
                "reasons": [reason.code for reason in result.reasons if reason.level != "show"],
            },
            expires_at=desk.now + OVERRIDE_FOR,
            command_id=command.command_id,
            created_at=desk.now,
        )
        try:
            async with desk.db.begin_nested():
                desk.db.add(seen)
                await desk.db.flush()
        except IntegrityError:
            raise DeskError(409, "That request was already used. Reload and try again.") from None
        await _audit(
            desk.db,
            desk.tenant_id,
            action="lead_desk.outreach.override_granted",
            resource_id=str(seen.id),
            payload={
                "lead_id": str(lead.id),
                "channel": command.channel,
                "reason_key": command.reason_key,
                "reason_text": seen.reason_text,
                "overrode": seen.verdict,
            },
            actor=desk.viewer.person_id,
            session_id=desk.viewer.session_id,
            now=desk.now,
        )
    elif seen.lead_id != lead.id:
        raise DeskError(409, "That request was already used for another lead.")
    names = await desk._names([seen.granted_by_person_id])
    return OverrideView(
        override_id=seen.id,
        lead_id=seen.lead_id,
        channel=seen.channel,
        reason_key=seen.reason_key,
        reason_text=seen.reason_text,
        granted_by_name=names.get(seen.granted_by_person_id, "A manager"),
        expires_at=seen.expires_at,
        used_at=seen.used_at,
        guard=await for_lead(desk, lead, seen.channel),
    )


# ----- outside senders (owners and admins) ---------------------------------------------------


def _org_manager(desk: LeadDesk) -> None:
    if not can(desk.viewer.role, "org.manage"):
        raise DeskError(403, "Owners and admins manage outreach senders.")


async def sender_views(desk: LeadDesk, rows: Sequence[LeadOutreachSender]) -> list[SenderView]:
    from ac_platform.integrations.models import IntegrationApiKey

    key_ids = {row.api_key_id for row in rows if row.api_key_id}
    prefixes: dict[UUID, str] = {}
    if key_ids:
        prefixes = dict(
            (
                await desk.db.execute(
                    select(IntegrationApiKey.id, IntegrationApiKey.prefix).where(
                        IntegrationApiKey.tenant_id == desk.tenant_id,
                        IntegrationApiKey.id.in_(key_ids),
                    )
                )
            )
            .tuples()
            .all()
        )
    week: dict[UUID, int] = {}
    if rows:
        counted_rows = (
            await desk.db.execute(
                select(LeadTouch.sender_id, func.count())
                .where(
                    LeadTouch.tenant_id == desk.tenant_id,
                    LeadTouch.sender_id.in_([row.id for row in rows]),
                    LeadTouch.sent_at > desk.now - WEEK,
                    LeadTouch.status.not_in(("queued", "expired")),
                )
                .group_by(LeadTouch.sender_id)
            )
        ).all()
        week = {sender: int(count) for sender, count in counted_rows if sender is not None}
    names = await desk._names({row.person_id for row in rows})
    return [
        SenderView(
            sender_id=row.id,
            key=row.key,
            label=row.label,
            kind=row.kind,
            person_id=row.person_id,
            person_name=names.get(row.person_id) if row.person_id else None,
            api_key_id=row.api_key_id,
            api_key_prefix=prefixes.get(row.api_key_id) if row.api_key_id else None,
            channels=tuple(row.channels or ()),
            lead_defaults=LeadDefaults(**(row.lead_defaults or {})),
            guard_mode=row.guard_mode,
            status=row.status,
            revision=row.revision,
            last_seen_at=row.last_seen_at,
            touches_week=int(week.get(row.id, 0)),
        )
        for row in rows
    ]


async def senders(desk: LeadDesk) -> Senders:
    _org_manager(desk)
    rows = (
        await desk.db.scalars(
            select(LeadOutreachSender)
            .where(LeadOutreachSender.tenant_id == desk.tenant_id)
            .order_by(LeadOutreachSender.created_at, LeadOutreachSender.id)
        )
    ).all()
    return Senders(senders=tuple(await sender_views(desk, rows)))


async def _bindable_key(desk: LeadDesk, key_id: UUID | None) -> None:
    from ac_platform.integrations.models import IntegrationApiKey

    if key_id is None:
        return
    row = await desk.db.scalar(
        select(IntegrationApiKey).where(
            IntegrationApiKey.id == key_id, IntegrationApiKey.tenant_id == desk.tenant_id
        )
    )
    if row is None or row.revoked_at is not None:
        raise DeskError(422, "Pick one of this workspace's API keys.")
    if not {"outreach:write"} & set(row.scopes or ()):
        raise DeskError(422, "That API key needs the outreach:write scope.")


async def _member(desk: LeadDesk, person_id: UUID) -> None:
    found = await desk.db.scalar(
        select(Membership.person_id).where(
            Membership.tenant_id == desk.tenant_id,
            Membership.person_id == person_id,
            Membership.status == "active",
            Membership.ended_at.is_(None),
        )
    )
    if found is None:
        raise DeskError(422, "Pick someone on the team.")


def _defaults(command: Any) -> dict[str, Any]:
    tags = [" ".join(str(tag).split())[:32] for tag in command.tags if str(tag).strip()][:3]
    return {"create": command.create, "side": command.side, "tags": tags, "assign": command.assign}


async def create_sender(desk: LeadDesk, command: SenderCommand) -> SenderView:
    _org_manager(desk)
    if (command.kind == "person_tool") != (command.person_id is not None):
        raise DeskError(
            422, "A person's own tool names the person it speaks for; an automation none."
        )
    if command.person_id is not None:
        await _member(desk, command.person_id)
    await _bindable_key(desk, command.api_key_id)
    same = await desk.db.scalar(
        select(LeadOutreachSender).where(
            LeadOutreachSender.tenant_id == desk.tenant_id, LeadOutreachSender.key == command.key
        )
    )
    if same is not None:
        raise DeskError(409, "A sender with that key is here already.")
    row = LeadOutreachSender(
        id=uuid4(),
        tenant_id=desk.tenant_id,
        key=command.key,
        label=" ".join(command.label.split()),
        kind=command.kind,
        person_id=command.person_id,
        api_key_id=command.api_key_id,
        channels=sorted(set(command.channels)),
        lead_defaults=_defaults(command.lead_defaults),
        guard_mode=command.guard_mode,
        status="active",
        revision=1,
        created_by_person_id=desk.viewer.person_id,
        created_at=desk.now,
        updated_at=desk.now,
    )
    try:
        async with desk.db.begin_nested():
            desk.db.add(row)
            await desk.db.flush()
    except IntegrityError:
        raise DeskError(409, "A sender with that key is here already.") from None
    await _audit(
        desk.db,
        desk.tenant_id,
        action="lead_desk.outreach.sender_created",
        resource_id=str(row.id),
        payload={
            "kind": row.kind,
            "channels": row.channels,
            "guard_mode": row.guard_mode,
            "person_id": str(row.person_id) if row.person_id else None,
            "api_key_id": str(row.api_key_id) if row.api_key_id else None,
        },
        actor=desk.viewer.person_id,
        session_id=desk.viewer.session_id,
        now=desk.now,
    )
    return (await sender_views(desk, [row]))[0]


async def _sender_row(desk: LeadDesk, sender_id: UUID, revision: int) -> LeadOutreachSender:
    row = await desk.db.scalar(
        select(LeadOutreachSender)
        .where(LeadOutreachSender.tenant_id == desk.tenant_id, LeadOutreachSender.id == sender_id)
        .with_for_update()
    )
    if row is None:
        raise DeskError(404, "This sender isn't here.")
    if row.revision != revision:
        raise DeskError(409, "Someone changed this sender. Reload and try again.")
    return row


async def edit_sender(desk: LeadDesk, sender_id: UUID, command: SenderEdit) -> SenderView:
    _org_manager(desk)
    row = await _sender_row(desk, sender_id, command.expected_revision)
    changed: list[str] = []
    if command.label is not None and command.label != row.label:
        row.label = " ".join(command.label.split())
        changed.append("label")
    if "api_key_id" in command.model_fields_set and command.api_key_id != row.api_key_id:
        await _bindable_key(desk, command.api_key_id)
        row.api_key_id = command.api_key_id
        changed.append("api_key_id")
    if command.channels is not None and sorted(set(command.channels)) != row.channels:
        row.channels = sorted(set(command.channels))
        changed.append("channels")
    if command.lead_defaults is not None and _defaults(command.lead_defaults) != row.lead_defaults:
        row.lead_defaults = _defaults(command.lead_defaults)
        changed.append("lead_defaults")
    if command.guard_mode is not None and command.guard_mode != row.guard_mode:
        row.guard_mode = command.guard_mode
        changed.append("guard_mode")
    if changed:
        row.revision += 1
        row.updated_at = desk.now
        await desk.db.flush()
        await _audit(
            desk.db,
            desk.tenant_id,
            action="lead_desk.outreach.sender_changed",
            resource_id=str(row.id),
            payload={"fields": changed, "revision": row.revision},
            actor=desk.viewer.person_id,
            session_id=desk.viewer.session_id,
            now=desk.now,
        )
        if "api_key_id" in changed:
            await _audit(
                desk.db,
                desk.tenant_id,
                action="lead_desk.outreach.sender_key_bound",
                resource_id=str(row.id),
                payload={"api_key_id": str(row.api_key_id) if row.api_key_id else None},
                actor=desk.viewer.person_id,
                session_id=desk.viewer.session_id,
                now=desk.now,
            )
    return (await sender_views(desk, [row]))[0]


async def pause_sender(desk: LeadDesk, sender_id: UUID, command: SenderPause) -> SenderView:
    _org_manager(desk)
    row = await _sender_row(desk, sender_id, command.expected_revision)
    status = "paused" if command.paused else "active"
    if row.status != status:
        row.status = status
        row.revision += 1
        row.updated_at = desk.now
        await desk.db.flush()
        await _audit(
            desk.db,
            desk.tenant_id,
            action="lead_desk.outreach.sender_paused"
            if command.paused
            else "lead_desk.outreach.sender_changed",
            resource_id=str(row.id),
            payload={"status": status, "revision": row.revision},
            actor=desk.viewer.person_id,
            session_id=desk.viewer.session_id,
            now=desk.now,
        )
    return (await sender_views(desk, [row]))[0]


def body_sha256(body: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def local_day(at: datetime, tz: ZoneInfo = IST) -> date:
    return at.astimezone(tz).date()


__all__ = [
    "CHANNELS",
    "Fact",
    "Facts",
    "Rules",
    "Window",
    "advance",
    "bulk",
    "check_lead",
    "counter_words",
    "guard",
    "parse_rules",
    "record_touch",
]


async def phone_calls(desk: LeadDesk, dialled: Sequence[tuple[Lead, LeadEvent]]) -> int:
    """The calls out a seller's phone logged by itself, as touches (one per line; a phone log
    can carry thousands of rows, so the guard is not read per call: calls are shown, and
    counted only when their mode says so)."""
    if not dialled:
        return 0
    _, config = await _settings(desk.db, desk.tenant_id)
    rules = parse_rules(config)
    mode = mode_for(rules, "call", "person")
    counts = counts_on("call", mode)
    record = {"verdict": "ok", "reasons": [], "mode": mode, "counts": counts}
    for lead, event in dialled:
        desk.db.add(
            LeadTouch(
                id=uuid4(),
                tenant_id=desk.tenant_id,
                lead_id=lead.id,
                channel="call",
                content_kind="call",
                initiated="outreach",
                sender_type="person",
                person_id=desk.viewer.person_id,
                via="phone",
                provider="phone",
                status="sent",
                status_at=event.created_at,
                sent_at=event.created_at,
                counted=counts,
                guard=dict(record),
                event_id=event.id,
                created_at=desk.now,
                updated_at=desk.now,
            )
        )
    return len(dialled)
