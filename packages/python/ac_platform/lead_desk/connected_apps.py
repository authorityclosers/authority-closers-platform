"""Settings → Connected apps: each app's health for one workspace, and a real test of each.

Owner, 20 Oct 2026 (through the orchestrator): every app can be tested from Settings.

The health is read from what the apps left in Sales Xray: the connected Pages, numbers
and accounts, the newest lead, message or call that arrived, the last error an app
recorded, and when the next pull is due. Webhook deliveries are not logged on their
own: the newest thing that arrived for this workspace is its last delivery.

The tests are real:
- lead ads: Meta makes a test lead on one of the Page's forms, and Sales Xray waits for
  it to reach Leads (up to a minute);
- WhatsApp: Meta's hello_world template (or, when they wrote in the last 24 hours, a
  short text) to a number the person gives, followed through sent, delivered and read;
- Messenger and Instagram: Meta is asked whether the Page sends its events to Sales
  Xray; only with an explicit confirm, a short test message goes into the latest
  conversation (inside Meta's 24-hour window);
- Google Ads: "Check now".
Lead stages (which of the business's stages its ad platforms hear about) have a card
too, read from the lead journey; they are set up on their own page in Leads.
Words are plain and never name a price or an amount.
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.identity.models import Person
from ac_platform.lead_desk.ai_replies import admin_settings
from ac_platform.lead_desk.connectors import google_ads_api as gads
from ac_platform.lead_desk.connectors import google_pull, meta, meta_pull
from ac_platform.lead_desk.journey import engine as journey_engine
from ac_platform.lead_desk.journey import mapping as journey_mapping
from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.models import (
    Lead,
    LeadAiReply,
    LeadDeskSettings,
    LeadEvent,
    LeadSocialAccount,
    LeadSocialMessage,
    LeadSource,
    LeadWhatsAppMessage,
)
from ac_platform.lead_desk.social import graph
from ac_platform.lead_desk.social import inbox as social_inbox
from ac_platform.lead_desk.store import PHONES_KEY, DeskError, LeadDesk, person_name, phone_health
from ac_platform.lead_desk.whatsapp import cloud
from ac_platform.lead_desk.whatsapp import inbox as wa_inbox

App = Literal[
    "meta_leads",
    "whatsapp",
    "messenger",
    "instagram",
    "google_ads",
    "lead_stages",
    "phone_calls",
    "webhook_sources",
    "ai_replies",
]
State = Literal["ready", "problem", "not_connected", "not_set_up", "off"]
TestStatus = Literal["waiting", "passed", "failed"]
Group = Literal["leads", "messaging", "ads", "calls", "automation"]

APPS: Final[tuple[App, ...]] = (
    "meta_leads",
    "whatsapp",
    "messenger",
    "instagram",
    "google_ads",
    "lead_stages",
    "phone_calls",
    "webhook_sources",
    "ai_replies",
)
NAMES: Final[dict[App, str]] = {
    "meta_leads": "Facebook & Instagram lead ads",
    "whatsapp": "WhatsApp",
    "messenger": "Messenger",
    "instagram": "Instagram messages",
    "google_ads": "Google Ads lead forms",
    "lead_stages": "Lead stages",
    "phone_calls": "Phone call logging (Sales Xray app)",
    "webhook_sources": "Webhooks and sheets",
    "ai_replies": "AI replies",
}
GROUPS: Final[dict[App, Group]] = {
    "meta_leads": "leads",
    "whatsapp": "messaging",
    "messenger": "messaging",
    "instagram": "messaging",
    "google_ads": "ads",
    "lead_stages": "ads",
    "phone_calls": "calls",
    "webhook_sources": "leads",
    "ai_replies": "automation",
}
# The existing connect routes (a browser navigation: they go to Meta or Google and come
# back), and each connection's existing disconnect route.
CONNECT: Final[dict[App, str]] = {
    "meta_leads": "/v1/lead-desk/meta/connect",
    "whatsapp": "/v1/lead-desk/whatsapp/start",
    "messenger": "/v1/lead-desk/messaging/connect",
    "instagram": "/v1/lead-desk/messaging/connect",
    "google_ads": "/v1/lead-desk/google/connect",
}
# Started from Settings → Connected apps, a connect comes back there:
# /settings/apps?connected=<card> or ?connect_error=<code> (connectors.app_return).
RETURN_QUERY: Final[str] = "?return_to=%2Fsettings%2Fapps&card="
DISCONNECT: Final[dict[App, str]] = {
    "meta_leads": "/v1/lead-desk/meta/pages/{id}/disconnect",
    "whatsapp": "/v1/lead-desk/whatsapp/numbers/{id}/disconnect",
    "messenger": "/v1/lead-desk/messaging/accounts/{id}/disconnect",
    "instagram": "/v1/lead-desk/messaging/accounts/{id}/disconnect",
    "google_ads": "/v1/lead-desk/google/accounts/{id}/disconnect",
}
NOT_SET_UP: Final[str] = "Not available here yet."
# What connecting gives, for a card not connected yet (admin-2, 20 Oct: not where to go).
GIVES: Final[dict[str, str]] = {
    "messenger": "Answer the messages people send your Facebook Page, in Chats.",
    "instagram": "Answer your Instagram messages, and reply to comments, in Chats.",
}
# A Sales Xray page where an app is set up, for a card with nothing to connect here.
PAGES: Final[dict[App, str]] = {"lead_stages": "/leads?tab=stages"}
LEAD_WAIT: Final[timedelta] = timedelta(seconds=60)
TEST_TEXT: Final[str] = "Test message from Sales Xray. No reply needed."
CLEAR_LABEL: Final[str] = "Clear the form's earlier test lead"
ASK_LABEL: Final[str] = "Ask Meta for a test lead"
WAIT_LABEL: Final[str] = "Wait for it in Leads"
_LEAD_TEST = re.compile(r"^lead-([0-9]{5,32})-([0-9]{9,11})$")
_WA_TEST = re.compile(r"^wa-([0-9a-f-]{36})$")


class _View(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Event(_View):
    at: datetime
    kind: Literal["lead", "message", "status", "comment", "call", "ai", "stage"]
    words: str


class Problem(_View):
    at: datetime | None = None
    words: str


class Link(_View):
    """An existing route the Settings card calls as it is (GET: open it in the page)."""

    method: Literal["GET", "POST"]
    path: str


class Connection(_View):
    id: str
    label: str
    detail: str | None = None
    state: State = "ready"
    words: str | None = None
    disconnect: Link | None = None


class TestOffer(_View):
    kind: str
    label: str
    needs: list[str] = []
    confirm: bool = False


class Webhook(_View):
    last_delivery_at: datetime | None = None


class AppHealth(_View):
    app: App
    name: str
    group: Group = "leads"
    state: State
    words: str
    configured: bool
    connect: Link | None = None
    page: str | None = None  # a Sales Xray page (a web path), opened in the app
    can_test: bool = False
    connections: list[Connection] = []
    last_event: Event | None = None
    last_error: Problem | None = None
    next_pull_at: datetime | None = None
    webhook: Webhook | None = None
    tests: list[TestOffer] = []


class Health(_View):
    checked_at: datetime
    apps: list[AppHealth]


class Step(_View):
    label: str
    state: Literal["done", "waiting", "failed", "skipped"]
    at: datetime | None = None
    words: str | None = None


class TestResult(_View):
    test_id: str | None = None
    app: App
    status: TestStatus
    words: str
    steps: list[Step] = []
    lead_id: UUID | None = None


def _epoch(value: object) -> datetime | None:
    return datetime.fromtimestamp(int(value), UTC) if isinstance(value, int | float) else None


def _newest(*values: datetime | None) -> datetime | None:
    found = [value for value in values if value is not None]
    return max(found) if found else None


def _state(configured: bool, connected: bool, problem: bool) -> State:
    if not configured:
        return "not_set_up"
    if not connected:
        return "not_connected"
    return "problem" if problem else "ready"


def _uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _and(names: list[str]) -> str:
    return " and ".join(names) if len(names) < 3 else ", ".join(names[:-1]) + " and " + names[-1]


# ----- health -------------------------------------------------------------------------


async def health(db: AsyncSession, tenant_id: UUID, *, now: datetime) -> Health:
    found = [
        await _meta_leads(db, tenant_id),
        await _whatsapp(db, tenant_id),
        await _social(db, tenant_id, "messenger"),
        await _social(db, tenant_id, "instagram"),
        await _google(db, tenant_id),
        await _lead_stages(db, tenant_id, now=now),
        await _phones(db, tenant_id),
        await _webhook_sources(db, tenant_id),
        await _ai_replies(db, tenant_id, now=now),
    ]
    return Health(checked_at=now, apps=[_card(app) for app in found])


def _card(app: AppHealth) -> AppHealth:
    """What a Settings card needs besides the health: its group, the existing connect
    and disconnect routes, and whether it has a test."""
    path = DISCONNECT.get(app.app)
    connections = [
        item.model_copy(
            update={
                "disconnect": Link(method="POST", path=path.format(id=item.id))
                if path and item.state != "off"
                else None
            }
        )
        for item in app.connections
    ]
    connect = CONNECT.get(app.app)
    return app.model_copy(
        update={
            "group": GROUPS[app.app],
            "connect": Link(method="GET", path=f"{connect}{RETURN_QUERY}{app.app}")
            if connect and app.configured
            else None,
            "page": PAGES.get(app.app),
            "can_test": bool(app.tests),
            "connections": connections,
        }
    )


async def _sources(db: AsyncSession, tenant_id: UUID, *kinds: str) -> list[LeadSource]:
    return list(
        (
            await db.scalars(
                select(LeadSource)
                .where(LeadSource.tenant_id == tenant_id, LeadSource.kind.in_(kinds))
                .order_by(LeadSource.created_at)
            )
        ).all()
    )


def _source_problem(source: LeadSource) -> Problem | None:
    error = (source.config or {}).get("last_error")
    if not isinstance(error, dict) or not error.get("text"):
        return None
    return Problem(at=_epoch(error.get("at")), words=str(error["text"])[:300])


async def _meta_leads(db: AsyncSession, tenant_id: UUID) -> AppHealth:
    configured = meta.config() is not None
    sources = await _sources(db, tenant_id, "meta")
    active = [source for source in sources if source.active]
    connections = []
    for source in sources:
        config = source.config or {}
        forms = config.get("forms", "all")
        problem = _source_problem(source)
        connections.append(
            Connection(
                id=str(config.get("page_id", "")),
                label=str(config.get("page_name") or source.label),
                detail=(
                    f"Forms: {'all' if forms == 'all' else len(forms or [])}"
                    f" · {_count(int(source.received or 0), 'lead', 'leads')}"
                ),
                state="off" if not source.active else "problem" if problem else "ready",
                words=problem.words if problem else None if source.active else "Switched off.",
            )
        )
    problems = [p for p in (_source_problem(s) for s in active) if p is not None]
    last = _newest(*(source.last_received_at for source in sources))
    pulls = [_epoch((s.config or {}).get("last_pulled_at")) for s in active]
    next_pull = min(
        (at + timedelta(seconds=meta_pull.PULL_EVERY) for at in pulls if at is not None),
        default=None,
    )
    state = _state(configured, bool(active), bool(problems))
    return AppHealth(
        app="meta_leads",
        name=NAMES["meta_leads"],
        state=state,
        words=NOT_SET_UP
        if not configured
        else "Bring in the leads from your Facebook and Instagram lead ads as they arrive."
        if not active
        else problems[0].words
        if problems
        else f"{_count(len(active), 'Page', 'Pages')} connected.",
        configured=configured,
        connections=connections,
        last_event=Event(at=last, kind="lead", words="New lead from Meta") if last else None,
        last_error=problems[0] if problems else None,
        next_pull_at=next_pull,
        webhook=Webhook(last_delivery_at=last) if active else None,
        tests=[TestOffer(kind="test_lead", label="Send a test lead", needs=["pageId", "formId"])]
        if active
        else [],
    )


async def _whatsapp(db: AsyncSession, tenant_id: UUID) -> AppHealth:
    configured = cloud.config() is not None
    rows = await wa_inbox.numbers(db, tenant_id)
    connections = []
    for row in rows:
        settings = wa_inbox.number_config(row)
        autos = [
            label
            for key, label in (("first_reply", "first reply"), ("out_of_hours", "after hours"))
            if isinstance(settings.get(key), dict) and settings[key].get("on")
        ]
        detail = " · ".join(
            part
            for part in (
                row.verified_name,
                f"quality {row.quality.lower()}" if row.quality else None,
                f"auto: {', '.join(autos)}" if autos else "no automatic replies",
            )
            if part
        )
        connections.append(Connection(id=str(row.id), label=row.display_number, detail=detail))
    base = LeadWhatsAppMessage.tenant_id == tenant_id
    inbound = await db.scalar(
        select(func.max(LeadWhatsAppMessage.created_at)).where(
            base, LeadWhatsAppMessage.direction == "in"
        )
    )
    status = await db.scalar(
        select(func.max(LeadWhatsAppMessage.status_at)).where(
            base,
            LeadWhatsAppMessage.direction == "out",
            LeadWhatsAppMessage.status.in_(("delivered", "read", "failed")),
        )
    )
    failed = await db.scalar(
        select(LeadWhatsAppMessage)
        .where(base, LeadWhatsAppMessage.status == "failed")
        .order_by(LeadWhatsAppMessage.created_at.desc())
        .limit(1)
    )
    auto_at = await db.scalar(
        select(func.max(LeadWhatsAppMessage.created_at)).where(
            base, LeadWhatsAppMessage.auto.in_(("first_reply", "out_of_hours"))
        )
    )
    last = _newest(inbound, status)
    event = None
    if last is not None:
        event = Event(
            at=last,
            kind="message" if last == inbound else "status",
            words="Message from a lead" if last == inbound else "Delivery update from WhatsApp",
        )
    problem = (
        Problem(
            at=failed.status_at or failed.created_at,
            words=f"A message didn't go: {failed.error_title or 'WhatsApp refused it'}.",
        )
        if failed is not None and (last is None or failed.created_at >= last - timedelta(days=1))
        else None
    )
    words = (
        NOT_SET_UP
        if not configured
        else "Message leads on WhatsApp and answer their replies in Chats."
        if not rows
        else f"{_count(len(rows), 'number', 'numbers')} connected."
        + (f" Last automatic reply {auto_at:%d %b %H:%M} UTC." if auto_at else "")
    )
    return AppHealth(
        app="whatsapp",
        name=NAMES["whatsapp"],
        state=_state(configured, bool(rows), problem is not None),
        words=words,
        configured=configured,
        connections=connections,
        last_event=event,
        last_error=problem,
        webhook=Webhook(last_delivery_at=last) if rows else None,
        tests=[TestOffer(kind="send_test", label="Send a test message", needs=["to"])]
        if rows
        else [],
    )


# Why the Page's last comment got no private reply (social.inbox.note_skip).
SKIP_WORDS: Final[dict[str, str]] = {
    "no_sender": "Meta didn't say who wrote it, so no private reply could go.",
    "from_page": "It was written as the Page itself; replies only go to other people.",
    "not_new": "It was an edit, not a new comment.",
    "bad_id": "Meta sent it in a form Sales Xray doesn't read.",
    "no_rule": "None of your comment rules' keywords was in it.",
}


def _skip_words(row: LeadSocialAccount, channel: str) -> str | None:
    skip = (row.config or {}).get(social_inbox.SKIP_KEY)
    if not isinstance(skip, dict) or skip.get("channel") != channel:
        return None
    why = SKIP_WORDS.get(str(skip.get("why")), "It wasn't one to answer.")
    at = str(skip.get("at") or "")[:16].replace("T", " ")
    return f"Last comment not answered ({at} UTC): {why}"


def _has_channel(account: LeadSocialAccount, channel: str) -> bool:
    return channel == "messenger" or bool(account.ig_user_id)


async def _social(db: AsyncSession, tenant_id: UUID, channel: App) -> AppHealth:
    configured = graph.config() is not None
    accounts = [
        row for row in await social_inbox.accounts(db, tenant_id) if _has_channel(row, str(channel))
    ]
    connections = [
        Connection(
            id=str(row.id),
            label=row.page_name
            if channel == "messenger"
            else f"@{row.ig_username or row.page_name}",
            detail=None if channel == "messenger" else f"via {row.page_name}",
            words=_skip_words(row, str(channel)),
        )
        for row in accounts
    ]
    base = (
        LeadSocialMessage.tenant_id == tenant_id,
        LeadSocialMessage.channel == channel,
    )
    newest = await db.scalar(
        select(LeadSocialMessage)
        .where(*base, LeadSocialMessage.direction == "in")
        .order_by(LeadSocialMessage.created_at.desc())
        .limit(1)
    )
    failed = await db.scalar(
        select(LeadSocialMessage)
        .where(*base, LeadSocialMessage.status == "failed")
        .order_by(LeadSocialMessage.created_at.desc())
        .limit(1)
    )
    last = newest.created_at if newest is not None else None
    problem = (
        Problem(
            at=failed.status_at or failed.created_at,
            words="A reply didn't go: "
            + (
                social_inbox.error_words(failed.error_title, failed.error_code, manager=True)
                or "Meta refused it."
            ),
        )
        if failed is not None and (last is None or failed.created_at >= last - timedelta(days=1))
        else None
    )
    where = "Messenger" if channel == "messenger" else "Instagram"
    return AppHealth(
        app=channel,
        name=NAMES[channel],
        state=_state(configured, bool(accounts), problem is not None),
        words=NOT_SET_UP
        if not configured
        else GIVES[channel]
        if not accounts
        else problem.words
        if problem
        else f"{_count(len(accounts), 'account', 'accounts')} connected.",
        configured=configured,
        connections=connections,
        last_event=Event(
            at=last,
            kind="comment" if newest is not None and newest.kind == "comment" else "message",
            words=f"{'Comment' if newest is not None and newest.kind == 'comment' else 'Message'}"
            f" on {where}",
        )
        if last is not None
        else None,
        last_error=problem,
        webhook=Webhook(last_delivery_at=last) if accounts else None,
        tests=[
            TestOffer(kind="check", label="Check the connection", needs=[]),
            TestOffer(kind="send_reply", label="Send a test reply", needs=[], confirm=True),
        ]
        if accounts
        else [],
    )


async def _google(db: AsyncSession, tenant_id: UUID) -> AppHealth:
    configured = gads.config() is not None
    sources = [s for s in await _sources(db, tenant_id, "webhook") if gads.is_connector(s)]
    active = [s for s in sources if s.active]
    connections = [
        Connection(
            id=str((s.config or {}).get("customer_id", "")),
            label=str((s.config or {}).get("account_name") or s.label),
            detail=_count(int(s.received or 0), "lead", "leads"),
            state="ready" if s.active else "off",
            words=None if s.active else "Switched off.",
        )
        for s in sources
    ]
    last = _newest(*(s.last_received_at for s in sources))
    pulls = [_epoch((s.config or {}).get("last_pulled_at")) for s in active]
    return AppHealth(
        app="google_ads",
        name=NAMES["google_ads"],
        state=_state(configured, bool(active), False),
        words=NOT_SET_UP
        if not configured
        else "Bring in the leads from your Google Ads lead forms as they arrive."
        if not active
        else f"{_count(len(active), 'account', 'accounts')} connected.",
        configured=configured,
        connections=connections,
        last_event=Event(at=last, kind="lead", words="New lead from Google Ads") if last else None,
        next_pull_at=min(
            (at + timedelta(seconds=google_pull.PULL_EVERY) for at in pulls if at is not None),
            default=None,
        ),
        webhook=Webhook(last_delivery_at=last) if active else None,
        tests=[TestOffer(kind="check_now", label="Check now", needs=[])] if active else [],
    )


async def _phones(db: AsyncSession, tenant_id: UUID) -> AppHealth:
    settings = await db.get(LeadDeskSettings, tenant_id)
    stored = (settings.config if settings else None) or {}
    raw = stored.get(PHONES_KEY)
    phones: dict[str, Any] = raw if isinstance(raw, dict) else {}
    ids = [UUID(key) for key in phones if _uuid(key)]
    people = (
        {
            str(person.id): person_name(person)
            for person in (await db.scalars(select(Person).where(Person.id.in_(ids)))).all()
        }
        if ids
        else {}
    )
    connections = []
    off = 0
    for person_id, entry in phones.items():
        report = phone_health(entry)
        if report is None:
            continue
        off += not report.call_log_on
        synced = f"synced {report.synced_at:%d %b %H:%M} UTC" if report.synced_at else "not synced"
        connections.append(
            Connection(
                id=person_id,
                label=people.get(person_id, "A teammate"),
                detail=f"Call log {'on' if report.call_log_on else 'off'} · {synced}",
                state="ready" if report.call_log_on else "problem",
                words=None if report.call_log_on else "Call logging is off on this phone.",
            )
        )
    last = await db.scalar(
        select(func.max(LeadEvent.created_at)).where(
            LeadEvent.tenant_id == tenant_id,
            LeadEvent.kind == "call",
            func.jsonb_extract_path_text(cast(LeadEvent.data, JSONB), "via") == "phone",
        )
    )
    return AppHealth(
        app="phone_calls",
        name=NAMES["phone_calls"],
        state=_state(True, bool(connections), off > 0),
        words="Log your team's calls from their phones with the Sales Xray app."
        if not connections
        else f"{_count(off, 'phone has', 'phones have')} call logging off."
        if off
        else f"{_count(len(connections), 'phone', 'phones')} logging calls.",
        configured=True,
        connections=connections,
        last_event=Event(at=last, kind="call", words="Call logged by a phone") if last else None,
        tests=[TestOffer(kind="report", label="Check the phones", needs=[])] if connections else [],
    )


async def _webhook_sources(db: AsyncSession, tenant_id: UUID) -> AppHealth:
    sources = [
        s for s in await _sources(db, tenant_id, "webhook", "sheet") if not gads.is_connector(s)
    ]
    connections = [
        Connection(
            id=str(s.id),
            label=s.label,
            detail=f"{s.kind} · {_count(int(s.received or 0), 'lead', 'leads')}"
            + (f" · last {s.last_received_at:%d %b %H:%M} UTC" if s.last_received_at else ""),
            state="ready" if s.active else "off",
            words=None if s.active else "Switched off.",
        )
        for s in sources
    ]
    last = _newest(*(s.last_received_at for s in sources))
    active = [s for s in sources if s.active]
    return AppHealth(
        app="webhook_sources",
        name=NAMES["webhook_sources"],
        state=_state(True, bool(active), False),
        words="Send leads in from your website, your other tools or a Google Sheet."
        if not active
        else f"{_count(len(active), 'source', 'sources')} on.",
        configured=True,
        connections=connections,
        last_event=Event(at=last, kind="lead", words="Lead from a webhook or sheet")
        if last
        else None,
        webhook=Webhook(last_delivery_at=last) if active else None,
        tests=[TestOffer(kind="report", label="Check deliveries", needs=[])] if active else [],
    )


async def _lead_stages(db: AsyncSession, tenant_id: UUID, *, now: datetime) -> AppHealth:
    """The same facts as GET /v1/lead-desk/journey/summary (the lead journey's own)."""
    row = await db.get(LeadDeskSettings, tenant_id)
    return lead_stages_card(
        await journeys.read(db, tenant_id),
        dict((row.config if row else None) or {}),
        await journey_engine.summary(db, tenant_id, now),
    )


def lead_stages_card(
    journey: journeys.Journey, config: Mapping[str, Any], facts: Mapping[str, Any]
) -> AppHealth:
    """Which ad platforms hear about the stages, what waits for the manager (a new stage
    to confirm), and a stage that hasn't reached a platform yet (it is tried again)."""
    platforms = journey_mapping.available()
    names = {p: journey_mapping.spec(p).name for p in platforms}
    settings = {p: journey_mapping.read(config, p) for p in platforms}
    on = [p for p in platforms if settings[p].ready]
    matches = {p: journey_mapping.matches(p, journey, settings[p]) for p in on}
    to_check = {
        p: sum(1 for m in matches[p] if m.state == "new" and m.suggested is not None) for p in on
    }
    waiting = facts.get("waiting_on") or {}
    retrying = [p for p in on if p in waiting]
    connections = []
    for p in platforms:
        mine = settings[p]
        if not mine.destination_id:
            continue
        new = to_check.get(p, 0)
        connections.append(
            Connection(
                id=p,
                label=names[p],
                detail=mine.destination_name,
                state="problem" if p in retrying or new else "ready" if mine.ready else "off",
                words=_platform_words(
                    names[p],
                    mine,
                    retrying=p in retrying,
                    new=new,
                    sending=sum(m.state == "on" for m in matches.get(p, [])),
                ),
            )
        )
    problems = [c for c in connections if c.state == "problem"]
    delivered = {p: at for p, at in (facts.get("last_delivered_at") or {}).items() if at}
    newest = max(delivered, key=lambda p: delivered[p], default=None)
    return AppHealth(
        app="lead_stages",
        name=NAMES["lead_stages"],
        state=_state(bool(platforms), bool(on), bool(problems)),
        words=NOT_SET_UP
        if not platforms
        else f"Tell {_and([names[p] for p in platforms])} which of your leads become"
        " customers, so your ads find more people like them."
        if not on
        else problems[0].words or ""
        if problems
        else f"{_count(len(journey.live), 'stage', 'stages')}"
        f" · sent to {_and([names[p] for p in on])}.",
        configured=bool(platforms),
        connections=connections,
        last_event=Event(
            at=delivered[newest],
            kind="stage",
            words=f"Lead stage sent to {names.get(newest, newest)}",
        )
        if newest is not None
        else None,
        last_error=Problem(words=f"A stage didn't reach {names[retrying[0]]} yet.")
        if retrying
        else None,
    )


def _platform_words(
    name: str, mine: journey_mapping.ProviderSettings, *, retrying: bool, new: int, sending: int
) -> str:
    if retrying:
        return f"A stage didn't reach {name} yet. Sales Xray tries again."
    if new:
        them = "it" if new == 1 else "them"
        stages = _count(new, "new stage", "new stages")
        return f"{stages} to confirm before {name} hears about {them}."
    if not mine.on:
        return "Switched off."
    if not mine.ready:
        return "No stages confirmed yet."
    return f"Sending {_count(sending, 'stage', 'stages')}."


async def _ai_replies(db: AsyncSession, tenant_id: UUID, *, now: datetime) -> AppHealth:
    config, _ = await admin_settings.read(db)
    enabled = bool(config["enabled"])
    paused = enabled and await admin_settings.capped(db, config, now)
    last = await db.scalar(
        select(func.max(LeadAiReply.created_at)).where(LeadAiReply.tenant_id == tenant_id)
    )
    return AppHealth(
        app="ai_replies",
        name=NAMES["ai_replies"],
        state="off" if not enabled else "problem" if paused else "ready",
        words="Switched off for now."
        if not enabled
        else "Paused for now."
        if paused
        else "On. Drafts replies to your leads from your business profile.",
        configured=enabled,
        last_event=Event(at=last, kind="ai", words="AI draft or reply") if last else None,
        tests=[TestOffer(kind="try", label="Try it", needs=["message"])]
        if enabled and not paused
        else [],
    )


# ----- tests ----------------------------------------------------------------------------


def meta_said(error: Exception) -> str:
    """Our words, then Meta's own and its code (owners and admins only see this)."""
    words = str(error)
    detail = getattr(error, "detail", None)
    code, subcode = getattr(error, "code", None), getattr(error, "subcode", None)
    if detail:
        words += f" Meta says: \u201c{detail}\u201d"
    if code is not None:
        words += f" (code {code}{f', subcode {subcode}' if subcode is not None else ''})"
    return words


def at_words(value: datetime | None) -> str | None:
    return f"{value:%d %b, %H:%M} UTC" if value is not None else None


def _require(configured: object) -> Any:
    if configured is None:
        raise DeskError(409, "This app isn't available here yet.")
    return configured


async def test_lead(desk: LeadDesk, page_id: str, form_id: str, *, api: Any = None) -> TestResult:
    """Meta makes a test lead on the form (its earlier one deleted first: Meta keeps one
    at a time); Sales Xray then waits for it in Leads."""
    cfg = _require(meta.config())
    if not re.fullmatch(r"[0-9]{5,32}", form_id):
        raise DeskError(422, "Pick one of the Page's forms.")
    source = next(
        (
            s
            for s in await _sources(desk.db, desk.tenant_id, "meta")
            if s.active and str((s.config or {}).get("page_id")) == page_id
        ),
        None,
    )
    if source is None:
        raise DeskError(404, "That Page isn't connected here.")
    token = meta.unseal(cfg.token_key, source.config["token"], page_id=page_id)
    client = api or meta.Graph(cfg)
    clear = CLEAR_LABEL
    try:
        earlier = await client.test_leads(form_id, token)
        for lead_id in earlier:
            await client.delete_lead(lead_id, token)
    except meta.MetaError as error:
        return TestResult(
            app="meta_leads",
            status="failed",
            words=f"Couldn't clear the form's earlier test lead. {meta_said(error)}",
            steps=[
                Step(label=clear, state="failed", words=meta_said(error)),
                Step(label=ASK_LABEL, state="skipped"),
                Step(label=WAIT_LABEL, state="skipped"),
            ],
        )
    cleared = Step(
        label=clear,
        state="done" if earlier else "skipped",
        at=desk.now,
        words=f"Deleted {_count(len(earlier), 'test lead', 'test leads')}."
        if earlier
        else "There was none.",
    )
    try:
        lead_id = await client.create_test_lead(form_id, token)
    except meta.MetaError as error:
        return TestResult(
            app="meta_leads",
            status="failed",
            words=f"Meta didn't make the test lead. {meta_said(error)}",
            steps=[
                cleared,
                Step(label=ASK_LABEL, state="failed", words=meta_said(error)),
                Step(label=WAIT_LABEL, state="skipped"),
            ],
        )
    started = int(time.time())
    result = await lead_status(desk, f"lead-{lead_id}-{started}")
    return result.model_copy(update={"steps": [cleared, *result.steps]})


async def lead_status(desk: LeadDesk, test_id: str) -> TestResult:
    found = _LEAD_TEST.fullmatch(test_id)
    if found is None:
        raise DeskError(404, "That test isn't here.")
    lead_id, started = found.group(1), datetime.fromtimestamp(int(found.group(2)), UTC)
    lead = await desk.db.scalar(
        select(Lead).where(
            Lead.tenant_id == desk.tenant_id, Lead.source == "meta", Lead.source_ref == lead_id
        )
    )
    made = Step(label=ASK_LABEL, state="done", at=started, words=at_words(started))
    if lead is not None:
        return TestResult(
            test_id=test_id,
            app="meta_leads",
            status="passed",
            words="The test lead reached Leads. Delete it from Leads when you're done.",
            steps=[
                made,
                Step(
                    label=WAIT_LABEL,
                    state="done",
                    at=lead.created_at,
                    words=f"Arrived {at_words(lead.created_at)}",
                ),
            ],
            lead_id=lead.id,
        )
    if desk.now - started > LEAD_WAIT:
        return TestResult(
            test_id=test_id,
            app="meta_leads",
            status="failed",
            words=(
                "Meta made the test lead, but it hasn't reached Leads in a minute: Meta isn't"
                " sending this Page's leads to Sales Xray. The 10-minute check will still"
                " bring it in."
            ),
            steps=[made, Step(label=WAIT_LABEL, state="failed", words="Not here after a minute.")],
        )
    return TestResult(
        test_id=test_id,
        app="meta_leads",
        status="waiting",
        words="Test lead made at Meta. Waiting for it to reach Leads (up to a minute).",
        steps=[made, Step(label=WAIT_LABEL, state="waiting")],
    )


async def test_whatsapp(
    desk: LeadDesk, to: str, number_id: UUID | None, *, api: Any = None
) -> TestResult:
    """hello_world (or a short text inside 24 hours) to the number the person gave."""
    cfg = _require(cloud.config())
    wa = cloud.wa_id(to)
    if wa is None:
        raise DeskError(422, "Enter the number with its country code, like +91 98765 43210.")
    rows = await wa_inbox.numbers(desk.db, desk.tenant_id)
    row = next((r for r in rows if number_id is None or r.id == number_id), None)
    if row is None:
        raise DeskError(404, "That WhatsApp number isn't connected here.")
    last_in = await desk.db.scalar(
        select(func.max(LeadWhatsAppMessage.created_at)).where(
            LeadWhatsAppMessage.tenant_id == desk.tenant_id,
            LeadWhatsAppMessage.wa_id == wa,
            LeadWhatsAppMessage.direction == "in",
        )
    )
    template = None
    if not cloud.window_open(last_in, desk.now):
        approved = await wa_inbox.approved_templates(desk.db, row)
        template = next(
            (t for t in approved if t.name == "hello_world" and t.language == "en_US"),
            next((t for t in approved if t.name == "hello_world"), None),
        )
        if template is None:
            raise DeskError(
                409,
                "Meta's hello_world template isn't approved on this number. Ask the test"
                " phone to send a message first, then try again within 24 hours.",
            )
    lead = await desk.db.scalar(
        select(Lead.id).where(Lead.tenant_id == desk.tenant_id, Lead.phone == f"+{wa}").limit(1)
    )
    message = LeadWhatsAppMessage(
        id=uuid4(),
        tenant_id=desk.tenant_id,
        number_id=row.id,
        lead_id=lead,
        wa_id=wa,
        direction="out",
        kind="template" if template else "text",
        body=template.name if template else TEST_TEXT,
        template_name=template.name if template else None,
        template_language=template.language if template else None,
        status="queued",
        sent_by_person_id=desk.viewer.person_id,
        auto=None,
        created_at=desk.now,
    )
    desk.db.add(message)
    client = api or cloud.Cloud(cfg)
    try:
        if template is None:
            message.wamid = await client.send_text(
                row.phone_number_id, wa_inbox.token(cfg, row), to=wa, body=TEST_TEXT
            )
        else:
            message.wamid = await client.send_template(
                row.phone_number_id,
                wa_inbox.token(cfg, row),
                to=wa,
                name=template.name,
                language=template.language,
                values=[],
            )
        message.status, message.status_at = "sent", desk.now
    except cloud.WhatsAppError as error:
        message.status = "failed"
        message.error_code = str(error.code) if error.code is not None else "refused"
        message.error_title = str(error)[:200]
    await desk.db.flush()
    return whatsapp_view(message)


def whatsapp_view(message: LeadWhatsAppMessage) -> TestResult:
    order = ("sent", "delivered", "read")
    reached = order.index(message.status) if message.status in order else -1
    steps = [
        Step(
            label=label,
            state="done" if reached >= i else "failed" if message.status == "failed" else "waiting",
            at=message.status_at if reached == i else None,
            words=at_words(message.status_at) if reached == i else None,
        )
        for i, label in enumerate(("Sent to WhatsApp", "Delivered to the phone", "Read"))
    ]
    test_id = f"wa-{message.id}"
    if message.status == "failed":
        return TestResult(
            test_id=test_id,
            app="whatsapp",
            status="failed",
            words=f"WhatsApp didn't send it: {message.error_title or 'refused'}.",
            steps=steps[:1],
        )
    if reached >= 1:
        return TestResult(
            test_id=test_id,
            app="whatsapp",
            status="passed",
            words="Delivered."
            + (" Read too." if reached == 2 else " Read shows when they open it."),
            steps=steps,
        )
    return TestResult(
        test_id=test_id,
        app="whatsapp",
        status="waiting",
        words="Sent. Waiting for WhatsApp to say it was delivered.",
        steps=steps,
    )


async def whatsapp_status(desk: LeadDesk, test_id: str) -> TestResult:
    found = _WA_TEST.fullmatch(test_id)
    message = await desk.db.get(LeadWhatsAppMessage, UUID(found.group(1))) if found else None
    if message is None or message.tenant_id != desk.tenant_id or message.direction != "out":
        raise DeskError(404, "That test isn't here.")
    return whatsapp_view(message)


async def test_social(
    desk: LeadDesk,
    channel: Literal["messenger", "instagram"],
    account_id: UUID | None,
    *,
    send_reply: bool,
    confirm: bool,
    api: Any = None,
) -> TestResult:
    """Meta is asked whether the Page sends its events to Sales Xray; a test reply only
    with an explicit confirm, into the newest conversation inside 24 hours."""
    cfg = _require(graph.config())
    accounts = [
        a for a in await social_inbox.accounts(desk.db, desk.tenant_id) if _has_channel(a, channel)
    ]
    account = next((a for a in accounts if account_id is None or a.id == account_id), None)
    if account is None:
        raise DeskError(404, "That account isn't connected here.")
    client = api or graph.Graph(cfg)
    token = graph.unseal(cfg, account.token, page_id=account.page_id)
    steps: list[Step] = []
    try:
        apps = await client.subscribed_apps(account.page_id, token)
    except graph.SocialError as error:
        steps.append(
            Step(label="Meta sends this Page's events", state="failed", words=meta_said(error))
        )
        return TestResult(app=channel, status="failed", words=meta_said(error), steps=steps)
    fields = apps.get(cfg.app_id, [])
    if "messages" not in fields:
        steps.append(Step(label="Meta sends this Page's events", state="failed"))
        return TestResult(
            app=channel,
            status="failed",
            words="Meta isn't sending this Page's messages to Sales Xray. Connect it again.",
            steps=steps,
        )
    steps.append(Step(label="Meta sends this Page's events", state="done", at=desk.now))
    newest = await desk.db.scalar(
        select(LeadSocialMessage)
        .where(
            LeadSocialMessage.tenant_id == desk.tenant_id,
            LeadSocialMessage.account_id == account.id,
            LeadSocialMessage.channel == channel,
            LeadSocialMessage.direction == "in",
            LeadSocialMessage.kind != "comment",
        )
        .order_by(LeadSocialMessage.created_at.desc())
        .limit(1)
    )
    steps.append(
        Step(
            label="Last message received",
            state="done",
            at=newest.created_at,
            words=at_words(newest.meta_time or newest.created_at),
        )
        if newest is not None
        else Step(label="Last message received", state="skipped", words="None yet.")
    )
    if send_reply:
        if not confirm:
            raise DeskError(422, "Confirm first: a real message goes to that person.")
        if (
            newest is None
            or newest.lead_id is None
            or not graph.window_open(newest.meta_time or newest.created_at, desk.now)
        ):
            steps.append(
                Step(
                    label="Test reply sent",
                    state="skipped",
                    words="No conversation in the last 24 hours to reply into.",
                )
            )
        else:
            sent = await social_inbox.send(
                desk,
                cfg,
                client,
                newest.lead_id,
                command_id=uuid4(),
                channel=channel,
                account_id=account.id,
                body=TEST_TEXT,
            )
            ok = getattr(sent, "status", None) == "sent"
            steps.append(
                Step(
                    label="Test reply sent",
                    state="done" if ok else "failed",
                    at=desk.now if ok else None,
                    words=None if ok else getattr(sent, "error_title", None),
                )
            )
    failed = any(step.state == "failed" for step in steps)
    return TestResult(
        app=channel,
        status="failed" if failed else "passed",
        words="The connection works." + ("" if newest else " No message has arrived yet."),
        steps=steps,
    )


async def test_google(
    desk: LeadDesk, customer_id: str | None, *, app_url: str, api: Any = None
) -> TestResult:
    """Check now: fetch the account's new leads and point new forms at Sales Xray."""
    cfg = _require(gads.config())
    sources = [
        s
        for s in await _sources(desk.db, desk.tenant_id, "webhook")
        if gads.is_connector(s) and s.active
    ]
    source = next(
        (
            s
            for s in sources
            if customer_id is None or str((s.config or {}).get("customer_id")) == customer_id
        ),
        None,
    )
    if source is None:
        raise DeskError(404, "That Google Ads account isn't connected here.")
    await desk.db.refresh(source, with_for_update=True)
    ads = api or gads.Ads(cfg)
    try:
        await google_pull.ensure_webhooks(source, ads, cfg, app_url=app_url)
        counts = await google_pull.pull_source(desk, source, ads, cfg, now=int(time.time()))
    except gads.GoogleAdsApiError as error:
        return TestResult(
            app="google_ads",
            status="failed",
            words=f"Google Ads didn't answer the check: {meta_said(error)}",
            steps=[Step(label="Checked Google Ads", state="failed", words=str(error))],
        )
    source.updated_at = desk.now
    await desk.db.flush()
    return TestResult(
        app="google_ads",
        status="passed",
        words=f"Checked. {_count(counts.fetched, 'lead form entry', 'lead form entries')}"
        f" found, {_count(counts.created, 'new lead', 'new leads')}.",
        steps=[Step(label="Checked Google Ads", state="done", at=desk.now)],
    )


def report(app: AppHealth) -> TestResult:
    """Apps nothing is sent to: what arrived and when, as a result."""
    ok = app.state == "ready"
    return TestResult(
        app=app.app,
        status="passed" if ok else "failed",
        words=app.words,
        steps=[
            Step(
                label=item.label,
                state="done" if item.state == "ready" else "failed",
                words=item.words or item.detail,
            )
            for item in app.connections
        ],
    )


async def test_status(desk: LeadDesk, test_id: str) -> TestResult:
    if test_id.startswith("lead-"):
        return await lead_status(desk, test_id)
    if test_id.startswith("wa-"):
        return await whatsapp_status(desk, test_id)
    raise DeskError(404, "That test isn't here.")
