"""Admin → Sellers → What happened (owner, 24 Oct 2026: "finding out what went wrong for a
seller is too hard ... Build one Admin screen that makes it obvious").

One person's days, newest first: the workspaces they belong to and which one each sign-in
opened, the app and version on each device, what reached the server (calls placed in the app
and calls the phone logged, results, notes, stage moves) beside what the phone reported doing
(calls started, results and stage moves saved, changes waiting or refused, errors shown, slow
taps, crashes), sign-ins and sign-outs, new installs and consent. A line at the top names the
newest gap. Counts, times and states only: never what a call, note or message said.

Every read is bounded and served by an index:

- the person by id; their memberships by person (``ix_memberships_person_status``, 50 at
  most) and those workspaces by id;
- sign-ins by person (``ix_sessions_person_id``), newest 500 in the window;
- lead events by workspace, actor and time (``ix_lead_desk_event_actor``), newest 5,000;
- Sales X-Ray telemetry by workspace, person and time
  (``ix_analytics_events_subject_occurred``), newest 20,000, never an expired row;
- each workspace's Lead Desk settings row by key (the phone entry it keeps per seller), and
  the analytics choices by resource (``ix_audit_events_resource``, sales_xray_consent.py).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select

from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
)
from ac_platform.identity.models import Person, Session
from ac_platform.lead_desk.models import LeadDeskSettings, LeadEvent
from ac_platform.lead_desk.store import PHONES_KEY
from ac_platform.learning.planning_models import AnalyticsEvent
from ac_platform.telemetry.admin_view import DEFAULT_SLOW_MS, INDIA, SLOW_MS, Row
from ac_platform.telemetry.sales_xray import RETENTION_POLICY_ID
from ac_platform.telemetry.sales_xray_consent import read_standing
from ac_platform.tenancy.models import Membership, Organisation, Tenant

SCHEMA = "ac.admin.seller-timeline/1"
DAYS = (7, 14, 30)
MAX_WORKSPACES = 50
MAX_SIGN_INS = 500
MAX_LEAD_EVENTS = 5_000
MAX_TELEMETRY = 20_000
MAX_MOMENTS = 40
LEAD_KINDS = ("call", "result", "note", "stage")
# The phone's side of the story; everything else in telemetry stays out of this read.
TELEMETRY_EVENTS = (
    "sx.action_timing",
    "sx.lead_stage_moved",
    "sx.writes_waiting",
    "sx.error_shown",
    "sx.js_error",
    "sx.api_slow",
    "sx.app_exit",
    "sx.web_vital",
    "sx.device_profile",
    "sx.app_launch",
    "sx.screen_viewed",
)
CRASHES = frozenset({"crash", "crash_native", "anr"})
STORES = {"play": "Play", "direct": "Download link"}


def _utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _day(moment: datetime) -> date:
    return moment.astimezone(INDIA).date()


def day_words(day: date) -> str:
    return f"{day.day} {day.strftime('%b')}"


def window_start(now: datetime, days: int) -> datetime:
    """Midnight in India at the start of the window's first day."""
    first = _day(now) - timedelta(days=days - 1)
    return datetime.combine(first, time(), INDIA).astimezone(UTC)


@dataclass(frozen=True)
class Seller:
    id: UUID
    name: str | None
    email: str | None
    status: str
    created_at: datetime
    terms_version: str | None
    terms_at: datetime | None


@dataclass(frozen=True)
class Member:
    tenant_id: UUID
    name: str
    kind: str
    role: str
    status: str
    joined_at: datetime
    ended_at: datetime | None
    # Usage analytics for this person here: "on", "off" (their choice or the workspace's)
    # or "sandbox" (never recorded).
    analytics: str
    analytics_changed_at: datetime | None


@dataclass(frozen=True)
class SignIn:
    at: datetime
    tenant_id: UUID | None
    last_seen_at: datetime | None
    ended_at: datetime | None


@dataclass(frozen=True)
class LeadRow:
    kind: str
    at: datetime
    tenant_id: UUID
    data: Mapping[str, Any]


@dataclass(frozen=True)
class Phone:
    """The phone entry Lead Desk keeps for a seller in a workspace (its latest report)."""

    tenant_id: UUID
    install: str | None
    app_version: str | None
    family: str | None
    reported_at: datetime | None
    synced_at: datetime | None


@dataclass
class Inputs:
    seller: Seller
    members: list[Member] = field(default_factory=list)
    sign_ins: list[SignIn] = field(default_factory=list)
    lead_events: list[LeadRow] = field(default_factory=list)
    telemetry: list[Row] = field(default_factory=list)
    phones: list[Phone] = field(default_factory=list)
    truncated: dict[str, bool] = field(default_factory=dict)


def _moment(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return _utc(datetime.fromisoformat(value))
    except ValueError:
        return None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def read(
    connection: Any,
    person_id: UUID,
    *,
    since: datetime,
    now: datetime,
    personal_tenant_id: UUID | None,
    operations_tenant_id: UUID | None,
) -> Inputs | None:
    """Everything the timeline shows for one person since ``since`` (a sync connection)."""
    person = connection.execute(
        select(
            Person.display_name,
            Person.first_name,
            Person.email,
            Person.status,
            Person.created_at,
            Person.consent_version,
            Person.consented_at,
        ).where(Person.id == person_id)
    ).first()
    if person is None:
        return None
    display, first, email, status, created, terms_version, terms_at = person
    inputs = Inputs(
        seller=Seller(
            id=person_id,
            name=display or first,
            email=email,
            status=str(getattr(status, "value", status)),
            created_at=_utc(created),
            terms_version=terms_version,
            terms_at=_utc(terms_at) if terms_at else None,
        )
    )
    memberships = connection.execute(
        select(
            Membership.tenant_id,
            Membership.role,
            Membership.status,
            Membership.created_at,
            Membership.ended_at,
            Tenant.name,
            Organisation.tenant_id,
            ConversationSandboxOrganisation.tenant_id,
        )
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .outerjoin(Organisation, Organisation.tenant_id == Membership.tenant_id)
        .outerjoin(
            ConversationSandboxOrganisation,
            ConversationSandboxOrganisation.tenant_id == Membership.tenant_id,
        )
        .where(Membership.person_id == person_id)
        .order_by(Membership.created_at)
        .limit(MAX_WORKSPACES + 1)
    ).all()
    inputs.truncated["workspaces"] = len(memberships) > MAX_WORKSPACES
    for tenant, role, state, joined, ended, name, organisation, sandbox in memberships[
        :MAX_WORKSPACES
    ]:
        if tenant == operations_tenant_id:
            kind = "operations"
        elif tenant == personal_tenant_id:
            kind = "personal"
        elif sandbox is not None:
            kind = "sandbox"
        elif organisation is not None:
            kind = "organisation"
        else:
            kind = "other"
        standing = read_standing(connection, tenant_id=tenant, person_id=person_id)
        changed = [item.at for item in (standing.person, standing.workspace) if item.at]
        inputs.members.append(
            Member(
                tenant_id=tenant,
                name="Personal accounts" if kind == "personal" else str(name),
                kind=kind,
                role=str(getattr(role, "value", role)),
                status=str(getattr(state, "value", state)),
                joined_at=_utc(joined),
                ended_at=_utc(ended) if ended else None,
                analytics=(
                    "sandbox" if standing.sandbox else "on" if standing.collecting else "off"
                ),
                analytics_changed_at=max(changed) if changed else None,
            )
        )
    tenants = [member.tenant_id for member in inputs.members]

    sessions = connection.execute(
        select(
            Session.created_at,
            Session.selected_tenant_id,
            Session.last_seen_at,
            Session.revoked_at,
        )
        .where(
            Session.person_id == person_id,
            Session.audience == "account",
            or_(Session.created_at >= since, Session.revoked_at >= since),
        )
        .order_by(Session.created_at.desc())
        .limit(MAX_SIGN_INS + 1)
    ).all()
    inputs.truncated["sign_ins"] = len(sessions) > MAX_SIGN_INS
    inputs.sign_ins = [
        SignIn(
            at=_utc(created),
            tenant_id=tenant,
            last_seen_at=_utc(seen) if seen else None,
            ended_at=_utc(revoked) if revoked else None,
        )
        for created, tenant, seen, revoked in sessions[:MAX_SIGN_INS]
    ]
    if not tenants:
        return inputs

    events = connection.execute(
        select(LeadEvent.kind, LeadEvent.created_at, LeadEvent.tenant_id, LeadEvent.data)
        .where(
            LeadEvent.tenant_id.in_(tenants),
            LeadEvent.actor_person_id == person_id,
            LeadEvent.created_at >= since,
            LeadEvent.created_at < now,
            LeadEvent.kind.in_(LEAD_KINDS),
        )
        .order_by(LeadEvent.created_at.desc())
        .limit(MAX_LEAD_EVENTS + 1)
    ).all()
    inputs.truncated["lead_events"] = len(events) > MAX_LEAD_EVENTS
    inputs.lead_events = [
        LeadRow(
            kind=str(kind),
            at=_utc(at),
            tenant_id=tenant,
            data=data if isinstance(data, dict) else {},
        )
        for kind, at, tenant, data in events[:MAX_LEAD_EVENTS]
    ]

    rows = connection.execute(
        select(
            AnalyticsEvent.event_name,
            AnalyticsEvent.occurred_at,
            AnalyticsEvent.release_id,
            AnalyticsEvent.tenant_id,
            AnalyticsEvent.session_id,
            AnalyticsEvent.payload,
        )
        .where(
            AnalyticsEvent.tenant_id.in_(tenants),
            AnalyticsEvent.subject_person_id == person_id,
            AnalyticsEvent.occurred_at >= since,
            AnalyticsEvent.occurred_at < now,
            AnalyticsEvent.retention_policy_id == RETENTION_POLICY_ID,
            AnalyticsEvent.retention_expires_at > now,
            AnalyticsEvent.event_name.in_(TELEMETRY_EVENTS),
        )
        .order_by(AnalyticsEvent.occurred_at.desc())
        .limit(MAX_TELEMETRY + 1)
    ).all()
    inputs.truncated["telemetry"] = len(rows) > MAX_TELEMETRY
    inputs.telemetry = [
        Row(
            event=str(name),
            at=_utc(at),
            release=str(release or ""),
            person=str(person_id),
            workspace=str(tenant),
            session=str(session) if session else None,
            payload=payload if isinstance(payload, dict) else {},
        )
        for name, at, release, tenant, session, payload in rows[:MAX_TELEMETRY]
    ]

    for tenant, config in connection.execute(
        select(LeadDeskSettings.tenant_id, LeadDeskSettings.config).where(
            LeadDeskSettings.tenant_id.in_(tenants)
        )
    ):
        phones = config.get(PHONES_KEY) if isinstance(config, dict) else None
        entry = phones.get(str(person_id)) if isinstance(phones, dict) else None
        if not isinstance(entry, dict):
            continue
        install = _text(entry.get("device_id"))
        inputs.phones.append(
            Phone(
                tenant_id=tenant,
                install=install[:8] if install else None,
                app_version=_text(entry.get("app_version")),
                family=_text(entry.get("family")),
                reported_at=_moment(entry.get("reported_at")),
                synced_at=_moment(entry.get("synced_at")),
            )
        )
    return inputs


@dataclass
class _Day:
    day: date
    calls_app: int = 0
    calls_logged: int = 0
    connected: int = 0
    test_calls: int = 0
    results: int = 0
    notes: int = 0
    stage_moves: int = 0
    phone_seen: bool = False
    calls_started: int = 0
    results_saved: int = 0
    moves_saved: int = 0
    waiting: int = 0
    refused: int = 0
    oldest_min: int = 0
    errors: Counter[str] = field(default_factory=Counter)
    script_errors: int = 0
    slow_taps: int = 0
    slow_requests: int = 0
    slow_screens: Counter[str] = field(default_factory=Counter)
    crashes: Counter[str] = field(default_factory=Counter)
    sign_ins: int = 0
    sign_outs: int = 0
    opened: set[str] = field(default_factory=set)
    versions: set[str] = field(default_factory=set)
    installs: set[str] = field(default_factory=set)
    new_installs: int = 0
    moments: list[tuple[datetime, str]] = field(default_factory=list)

    @property
    def calls(self) -> int:
        return self.calls_app + self.calls_logged

    @property
    def active(self) -> bool:
        return bool(
            self.calls
            or self.test_calls
            or self.results
            or self.notes
            or self.stage_moves
            or self.phone_seen
            or self.sign_ins
            or self.sign_outs
            or self.moments
        )


def _number(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0


def _plural(count: int, one: str, many: str | None = None) -> str:
    return f"{count:,} {one if count == 1 else (many or one + 's')}"


def _age(minutes: int) -> str:
    if minutes < 60:
        return _plural(minutes, "min", "min")
    if minutes < 48 * 60:
        return _plural(round(minutes / 60), "hour")
    return _plural(round(minutes / 1_440), "day")


def _clock(moment: datetime) -> str:
    return moment.astimezone(INDIA).strftime("%H:%M")


def _flags(day: _Day) -> list[tuple[str, str]]:
    """What went wrong that day, worst first: ("bad" | "warn", words)."""
    flags: list[tuple[str, str]] = []
    if day.results_saved > day.results:
        flags.append(
            (
                "bad",
                f"{_plural(day.results_saved, 'result')} saved on the phone, "
                f"{day.results:,} reached the server",
            )
        )
    if day.moves_saved > day.stage_moves:
        flags.append(
            (
                "bad",
                f"{_plural(day.moves_saved, 'stage move')} saved on the phone, "
                f"{day.stage_moves:,} reached the server",
            )
        )
    if day.calls and not day.results and day.results_saved <= day.results:
        flags.append(
            (
                "warn",
                f"{_plural(day.calls, 'call')}, no results reached the server"
                + (
                    "; none were saved on the phone either"
                    if day.phone_seen
                    else "; the phone sent no usage data that day"
                ),
            )
        )
    if day.refused:
        flags.append(
            (
                "bad",
                f"{_plural(day.refused, 'change')} refused when the phone sent "
                f"{'it' if day.refused == 1 else 'them'} again",
            )
        )
    if day.waiting:
        flags.append(
            (
                "warn",
                f"The phone held {_plural(day.waiting, 'unsent change')}"
                + (f" (oldest {_age(day.oldest_min)})" if day.oldest_min else ""),
            )
        )
    crashes = sum(day.crashes.values())
    if crashes:
        flags.append(("bad", f"The app crashed or froze {_plural(crashes, 'time')}"))
    errors = sum(day.errors.values())
    if errors:
        top = ", ".join(code for code, _ in day.errors.most_common(3))
        flags.append(("warn", f"{_plural(errors, 'error')} shown ({top})"))
    if day.new_installs:
        flags.append(("warn", "A new install or a new phone started logging calls"))
    return sorted(flags, key=lambda flag: flag[0] != "bad")


def _why(day: _Day) -> str:
    """The summary's reason for the worst day, in plain words."""
    if day.results_saved > day.results:
        missing = day.results_saved - day.results
        return f"the phone saved {_plural(missing, 'result')} that never reached the server"
    if day.waiting:
        return f"the phone held {_plural(day.waiting, 'change')} it didn't send"
    if day.refused:
        return f"the server refused {_plural(day.refused, 'change')} the phone sent again"
    if day.calls and not day.results:
        return (
            "none were saved on the phone either"
            if day.phone_seen
            else "the phone sent no usage data that day"
        )
    words = _flags(day)[0][1]
    return words[0].lower() + words[1:]


def build(inputs: Inputs, *, now: datetime, days: int) -> dict[str, Any]:
    since = window_start(now, days)
    names = {member.tenant_id: member.name for member in inputs.members}
    by_day: dict[date, _Day] = {}

    def at(moment: datetime) -> _Day | None:
        if not since <= moment < now:
            return None
        key = _day(moment)
        if key not in by_day:
            by_day[key] = _Day(day=key)
        return by_day[key]

    def opened(tenant: UUID | str | None) -> str | None:
        if tenant is None:
            return None
        try:
            return names.get(tenant if isinstance(tenant, UUID) else UUID(tenant))
        except ValueError:
            return None

    for sign_in in inputs.sign_ins:
        day = at(sign_in.at)
        place = opened(sign_in.tenant_id)
        if day is not None:
            day.sign_ins += 1
            if place:
                day.opened.add(place)
            day.moments.append((sign_in.at, "Signed in" + (f", opened {place}" if place else "")))
        if sign_in.ended_at is not None:
            ended = at(sign_in.ended_at)
            if ended is not None:
                ended.sign_outs += 1
                ended.moments.append((sign_in.ended_at, "Signed out"))

    # Installs: the phone's own id rides on every call it logs, so a new id is a new install.
    installs: dict[str, tuple[datetime, datetime, int]] = {}
    for event in sorted(inputs.lead_events, key=lambda item: item.at):
        day = at(event.at)
        if day is None:
            continue
        data = event.data
        if event.kind == "call":
            if data.get("recording") is True:
                continue
            if data.get("via") == "phone":
                day.calls_logged += 1
                day.connected += data.get("connected") is True
                install = _text(data.get("device_id"))
                if install:
                    short = install[:8]
                    day.installs.add(short)
                    first, _last, count = installs.get(short, (event.at, event.at, 0))
                    if short not in installs and installs:
                        day.new_installs += 1
                        day.moments.append((event.at, f"New install {short} logged its first call"))
                    installs[short] = (first, event.at, count + 1)
            elif data.get("simulated") is True:
                day.test_calls += 1
            else:
                day.calls_app += 1
        elif event.kind == "result":
            day.results += 1
        elif event.kind == "note":
            day.notes += 1
        elif event.kind == "stage":
            day.stage_moves += 1

    devices: dict[tuple[str, str], dict[str, Any]] = {}
    previous_waiting: tuple[int, int] = (0, 0)
    for row in sorted(inputs.telemetry, key=lambda item: item.at):
        day = at(row.at)
        if day is None:
            continue
        payload = row.payload
        day.phone_seen = True
        version = _text(payload.get("app_version"))
        if version:
            day.versions.add(version)
        place = opened(row.workspace)
        if place:
            day.opened.add(place)
        app = _text(payload.get("app")) or "web"
        kind = _text(payload.get("device")) or "unknown"
        device = devices.setdefault(
            (app, kind),
            {
                "app": app,
                "device": kind,
                "version": None,
                "versions": [],
                "model": None,
                "maker": None,
                "store": None,
                "android": None,
                "last_seen_at": None,
            },
        )
        device["last_seen_at"] = row.at
        if version:
            device["version"] = version
            if version not in device["versions"]:
                device["versions"].append(version)
        if row.event == "sx.action_timing":
            action = _text(payload.get("action")) or "other"
            if action == "call_start":
                day.calls_started += 1
            elif action == "outcome_save":
                day.results_saved += 1
            ms = _number(payload, "ms")
            if payload.get("result") == "timeout" or ms > SLOW_MS.get(action, DEFAULT_SLOW_MS):
                day.slow_taps += 1
        elif row.event == "sx.lead_stage_moved":
            day.moves_saved += 1
        elif row.event == "sx.writes_waiting":
            waiting, refused = _number(payload, "waiting"), _number(payload, "refused")
            day.waiting = max(day.waiting, waiting)
            day.refused = max(day.refused, refused)
            day.oldest_min = max(day.oldest_min, _number(payload, "oldest_min"))
            if (waiting, refused) != previous_waiting:
                words = (
                    f"Phone reported {_plural(waiting, 'change')} waiting"
                    + (f", {refused:,} refused" if refused else "")
                    if waiting or refused
                    else "Phone reported every change sent"
                )
                day.moments.append((row.at, words))
            previous_waiting = (waiting, refused)
        elif row.event == "sx.error_shown":
            code = _text(payload.get("code")) or "unknown"
            surface = _text(payload.get("surface"))
            day.errors[f"{surface}: {code}" if surface else code] += 1
        elif row.event == "sx.js_error":
            day.script_errors += 1
        elif row.event == "sx.api_slow":
            day.slow_requests += 1
        elif row.event == "sx.app_exit":
            reason = _text(payload.get("reason")) or "other"
            if reason in CRASHES:
                day.crashes[reason] += 1
                day.moments.append(
                    (row.at, f"App reported it last closed: {reason.replace('_', ' ')}")
                )
        elif row.event == "sx.web_vital":
            if payload.get("metric") == "lcp" and payload.get("rating") == "poor":
                day.slow_screens[_text(payload.get("screen")) or "unknown"] += 1
        elif row.event == "sx.device_profile":
            device["model"] = _text(payload.get("model_label")) or device["model"]
            device["maker"] = _text(payload.get("maker")) or device["maker"]
            store = _text(payload.get("store"))
            device["store"] = STORES.get(store, device["store"]) if store else device["store"]
            android = _number(payload, "android")
            device["android"] = android or device["android"]

    for member in inputs.members:
        if member.analytics_changed_at is not None:
            day = at(member.analytics_changed_at)
            if day is not None:
                day.moments.append(
                    (
                        member.analytics_changed_at,
                        f"Usage analytics in {member.name} now {member.analytics}",
                    )
                )

    ordered = sorted((day for day in by_day.values() if day.active), key=lambda d: d.day)
    previous_versions: set[str] = set()
    for day in ordered:
        fresh = day.versions - previous_versions
        if previous_versions and fresh:
            day.moments.append(
                (
                    datetime.combine(day.day, time(), INDIA).astimezone(UTC),
                    f"App version now {', '.join(sorted(fresh))}",
                )
            )
        previous_versions = day.versions or previous_versions

    day_rows = []
    flagged: list[tuple[_Day, list[tuple[str, str]]]] = []
    for day in reversed(ordered):
        flags = _flags(day)
        if flags:
            flagged.append((day, flags))
        moments = sorted(day.moments)[:MAX_MOMENTS]
        day_rows.append(
            {
                "day": day.day.isoformat(),
                "label": day_words(day.day),
                "server": {
                    "calls_app": day.calls_app,
                    "calls_logged": day.calls_logged,
                    "connected": day.connected,
                    "test_calls": day.test_calls,
                    "results": day.results,
                    "notes": day.notes,
                    "stage_moves": day.stage_moves,
                },
                "phone": (
                    {
                        "calls_started": day.calls_started,
                        "results_saved": day.results_saved,
                        "stage_moves_saved": day.moves_saved,
                        "waiting": day.waiting,
                        "refused": day.refused,
                        "oldest_waiting_min": day.oldest_min,
                        "errors": sum(day.errors.values()),
                        "error_codes": [code for code, _ in day.errors.most_common(3)],
                        "script_errors": day.script_errors,
                        "slow_taps": day.slow_taps,
                        "slow_requests": day.slow_requests,
                        "slow_screens": [name for name, _ in day.slow_screens.most_common(3)],
                        "crashes": sum(day.crashes.values()),
                    }
                    if day.phone_seen
                    else None
                ),
                "sign_ins": day.sign_ins,
                "sign_outs": day.sign_outs,
                "workspaces": sorted(day.opened),
                "versions": sorted(day.versions),
                "installs": sorted(day.installs),
                "flags": [{"tone": tone, "words": words} for tone, words in flags],
                "moments": [
                    {"at": moment.isoformat(), "time": _clock(moment), "words": words}
                    for moment, words in moments
                ],
            }
        )

    worst = next((item for item in flagged if item[1][0][0] == "bad"), None) or next(
        iter(flagged), None
    )
    if worst is not None:
        day, flags = worst
        others = len(flagged) - 1
        summary = (
            f"{day_words(day.day)}: {_plural(day.calls, 'call')}, "
            f"{_plural(day.results, 'result')} saved — {_why(day)}"
            + (f" (gaps on {_plural(others, 'other day')})" if others else "")
        )
        tone = flags[0][0]
    elif ordered:
        calls = sum(day.calls for day in ordered)
        results = sum(day.results for day in ordered)
        moves = sum(day.stage_moves for day in ordered)
        summary = (
            f"No gaps in the last {days} days: {_plural(calls, 'call')}, "
            f"{_plural(results, 'result')} and {_plural(moves, 'stage move')} "
            "reached the server"
        )
        tone = "good"
    else:
        summary = f"No activity in the last {days} days"
        tone = "neutral"

    seller = inputs.seller
    totals = {
        "calls_app": sum(day.calls_app for day in ordered),
        "calls_logged": sum(day.calls_logged for day in ordered),
        "results": sum(day.results for day in ordered),
        "notes": sum(day.notes for day in ordered),
        "stage_moves": sum(day.stage_moves for day in ordered),
        "results_saved": sum(day.results_saved for day in ordered),
        "stage_moves_saved": sum(day.moves_saved for day in ordered),
        "crashes": sum(sum(day.crashes.values()) for day in ordered),
        "errors": sum(sum(day.errors.values()) for day in ordered),
        "days_with_gaps": len(flagged),
    }
    opened_count = Counter(
        sign_in.tenant_id for sign_in in inputs.sign_ins if since <= sign_in.at < now
    )
    last_opened: dict[UUID, datetime] = {}
    for sign_in in inputs.sign_ins:
        if sign_in.tenant_id is not None:
            moment = sign_in.last_seen_at or sign_in.at
            last_opened[sign_in.tenant_id] = max(last_opened.get(sign_in.tenant_id, moment), moment)
    return {
        "schema": SCHEMA,
        "person": {
            "id": str(seller.id),
            "name": seller.name,
            "email": seller.email,
            "status": seller.status,
            "created_at": seller.created_at.isoformat(),
        },
        "window": {"days": days, "since": since.isoformat(), "until": now.isoformat()},
        "summary": {"tone": tone, "words": summary},
        "totals": totals,
        "workspaces": [
            {
                "id": str(member.tenant_id),
                "name": member.name,
                "kind": member.kind,
                "role": member.role,
                "status": member.status,
                "joined_at": member.joined_at.isoformat(),
                "ended_at": member.ended_at.isoformat() if member.ended_at else None,
                "analytics": member.analytics,
                "sign_ins": opened_count.get(member.tenant_id, 0),
                "last_opened_at": (
                    last_opened[member.tenant_id].isoformat()
                    if member.tenant_id in last_opened
                    else None
                ),
            }
            for member in inputs.members
        ],
        "devices": [
            {
                **device,
                "versions": list(reversed(device["versions"])),
                "last_seen_at": device["last_seen_at"].isoformat(),
            }
            for device in sorted(
                devices.values(), key=lambda item: item["last_seen_at"], reverse=True
            )
        ],
        "phones": [
            {
                "workspace": names.get(phone.tenant_id),
                "install": phone.install,
                "app_version": phone.app_version,
                "family": phone.family,
                "reported_at": phone.reported_at.isoformat() if phone.reported_at else None,
                "synced_at": phone.synced_at.isoformat() if phone.synced_at else None,
            }
            for phone in inputs.phones
        ],
        "installs": [
            {
                "install": short,
                "first_call_at": first.isoformat(),
                "last_call_at": last.isoformat(),
                "calls": count,
            }
            for short, (first, last, count) in sorted(
                installs.items(), key=lambda item: item[1][1], reverse=True
            )
        ],
        "consent": {
            "terms_version": seller.terms_version,
            "terms_at": seller.terms_at.isoformat() if seller.terms_at else None,
        },
        "days": day_rows,
        "truncated": sorted(key for key, value in inputs.truncated.items() if value),
    }
