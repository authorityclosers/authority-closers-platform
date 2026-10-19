"""Messenger and Instagram in the Sales Xray CRM: Pages, conversations, sending, comments.

- A message from someone new becomes a lead through ``LeadDesk.ingest`` (so the
  organisation's allocation rules pick the seller); later messages go on that lead's
  conversation. Each message is stored once (Meta's message id).
- The lead's owner or a manager replies inside Meta's 24-hour window; later, a person
  may answer up to 7 days on with Meta's Human Agent tag, when the organisation has it
  on. Automations never use the tag. Every send is a ``message`` event on the lead's
  history (never its words), which stops the first-response clock when a person sent it.
- Comment to message: a comment on the Page's post or the Instagram account's media
  that has one of a rule's keywords gets one private reply (and, if the rule says so, a
  short public answer), and the commenter becomes a lead.
- Auto replies per Page: an instant first reply to someone writing for the first time,
  and a reply to messages that arrive outside work hours.

Message words are the customer's own data: they live only in
``lead_desk_social_messages`` and are emptied when the lead leaves Lead Desk, or when the
person takes a message back.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import and_, exists, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.lead_desk import hours as work_hours
from ac_platform.lead_desk.models import (
    Lead,
    LeadDeskSettings,
    LeadEvent,
    LeadSocialAccount,
    LeadSocialMessage,
)
from ac_platform.lead_desk.social import graph
from ac_platform.lead_desk.store import DeskError, LeadDesk, Viewer

STATUS_ORDER: Final[dict[str, int]] = {"queued": 0, "sent": 1, "delivered": 2, "read": 3}
FIRST_REPLY_WITHIN: Final[timedelta] = timedelta(minutes=10)
OUT_OF_HOURS_EVERY: Final[timedelta] = timedelta(hours=12)
CONVERSATION_LIMIT: Final[int] = 200
INBOX_LIMIT: Final[int] = 100
MAX_PAGES: Final[int] = 25
MAX_RULES: Final[int] = 20
MAX_KEYWORDS: Final[int] = 10
LABELS: Final[dict[str, str]] = {"messenger": "Messenger", "instagram": "Instagram"}
DEFAULT_CONFIG: Final[dict[str, Any]] = {
    "messenger": True,
    "instagram": True,
    "human_agent": False,
    "first_reply": {"on": False, "text": None},
    "out_of_hours": {"on": False, "text": None},
    "comments": [],
}


def account_config(row: LeadSocialAccount) -> dict[str, Any]:
    raw = row.config if isinstance(row.config, dict) else {}
    found = raw.get("comments")
    rules: list[Any] = found if isinstance(found, list) else []
    return {
        "messenger": raw.get("messenger") is not False,
        "instagram": raw.get("instagram") is not False and row.ig_user_id is not None,
        "human_agent": raw.get("human_agent") is True,
        "first_reply": {**DEFAULT_CONFIG["first_reply"], **(raw.get("first_reply") or {})},
        "out_of_hours": {**DEFAULT_CONFIG["out_of_hours"], **(raw.get("out_of_hours") or {})},
        "comments": [dict(rule) for rule in rules if isinstance(rule, Mapping)][:MAX_RULES],
    }


def label(row: LeadSocialAccount, channel: str) -> str:
    if channel == "instagram" and row.ig_username:
        return f"Instagram · @{row.ig_username}"[:120]
    return f"{LABELS.get(channel, 'Messenger')} · {row.page_name}"[:120]


def _system(row: LeadSocialAccount, db: AsyncSession, now: datetime) -> LeadDesk:
    return LeadDesk(
        db,
        Viewer(
            person_id=row.connected_by_person_id,
            tenant_id=row.tenant_id,
            role="system",
            name="Messaging",
        ),
        now=now,
    )


# ----- Pages ---------------------------------------------------------------------------


async def accounts(
    db: AsyncSession, tenant_id: UUID, *, active: bool = True
) -> list[LeadSocialAccount]:
    query = select(LeadSocialAccount).where(LeadSocialAccount.tenant_id == tenant_id)
    if active:
        query = query.where(LeadSocialAccount.status == "active")
    return list((await db.scalars(query.order_by(LeadSocialAccount.created_at))).all())


async def account(db: AsyncSession, tenant_id: UUID, account_id: UUID) -> LeadSocialAccount:
    row = await db.get(LeadSocialAccount, account_id)
    if row is None or row.tenant_id != tenant_id or row.status != "active":
        raise DeskError(404, "That Page isn't connected here.")
    return row


def page_token(cfg: graph.SocialConfig, row: LeadSocialAccount) -> str:
    return graph.unseal(cfg, row.token, page_id=row.page_id)


@dataclass(slots=True)
class Connected:
    accounts: list[LeadSocialAccount] = field(default_factory=list)
    taken: list[str] = field(default_factory=list)  # Pages another organisation has


async def connect_pages(
    desk: LeadDesk, cfg: graph.SocialConfig, api: graph.Graph, pages: Sequence[graph.Page]
) -> Connected:
    """Keep each shared Page with its sealed token; its messages come to Sales Xray."""
    desk._require_manager()
    out = Connected()
    for page in list(pages)[:MAX_PAGES]:
        elsewhere = await desk.db.scalar(
            select(LeadSocialAccount.tenant_id).where(
                LeadSocialAccount.page_id == page.page_id,
                LeadSocialAccount.status == "active",
                LeadSocialAccount.tenant_id != desk.tenant_id,
            )
        )
        if elsewhere is not None:
            out.taken.append(page.name)
            continue
        await api.subscribe(page.page_id, page.token)
        row = await desk.db.scalar(
            select(LeadSocialAccount)
            .where(
                LeadSocialAccount.tenant_id == desk.tenant_id,
                LeadSocialAccount.page_id == page.page_id,
                LeadSocialAccount.status == "active",
            )
            .with_for_update()
        )
        if row is None:
            row = LeadSocialAccount(
                id=uuid4(),
                tenant_id=desk.tenant_id,
                page_id=page.page_id,
                status="active",
                config={},
                connected_by_person_id=desk.viewer.person_id,
                created_at=desk.now,
            )
            desk.db.add(row)
        row.page_name = page.name
        row.ig_user_id = page.ig_user_id
        row.ig_username = page.ig_username
        row.token = graph.seal(cfg, page.token, page_id=page.page_id)
        row.updated_at = desk.now
        out.accounts.append(row)
    await desk.db.flush()
    return out


async def disconnect(desk: LeadDesk, account_id: UUID) -> None:
    desk._require_manager()
    row = await account(desk.db, desk.tenant_id, account_id)
    row.status = "disconnected"
    row.disconnected_at = desk.now
    row.updated_at = desk.now
    await desk.db.flush()


def save_settings(row: LeadSocialAccount, settings: Mapping[str, Any]) -> None:
    """A manager's channels, auto replies and comment rules for one Page."""
    first = dict(settings.get("first_reply") or {})
    late = dict(settings.get("out_of_hours") or {})
    for part, words in ((first, "the first reply"), (late, "messages that arrive after hours")):
        value = str(part.get("text") or "").strip()
        if part.get("on") and not value:
            raise DeskError(422, f"Write the reply for {words}.")
        part["text"] = value[:1000] or None
    rules: list[dict[str, Any]] = []
    for raw in list(settings.get("comments") or [])[:MAX_RULES]:
        keywords = [
            str(word).strip()[:60] for word in (raw.get("keywords") or []) if str(word).strip()
        ][:MAX_KEYWORDS]
        reply = str(raw.get("reply") or "").strip()[:1000]
        public = str(raw.get("public_reply") or "").strip()[:300] or None
        if not keywords:
            raise DeskError(422, "Give each comment rule at least one keyword.")
        if not reply:
            raise DeskError(422, "Write the private message each comment rule sends.")
        rules.append(
            {
                "on": raw.get("on") is not False,
                "keywords": keywords,
                "reply": reply,
                "public_reply": public,
            }
        )
    row.config = {
        "messenger": settings.get("messenger") is not False,
        "instagram": settings.get("instagram") is not False,
        "human_agent": settings.get("human_agent") is True,
        "first_reply": {"on": bool(first.get("on")), "text": first["text"]},
        "out_of_hours": {"on": bool(late.get("on")), "text": late["text"]},
        "comments": rules,
    }


# ----- receiving -------------------------------------------------------------------------


@dataclass(slots=True)
class Received:
    messages: int = 0
    leads_created: int = 0
    statuses: int = 0
    comments: int = 0
    unsent: int = 0
    skipped: list[str] = field(default_factory=list)  # why comments weren't taken


SKIP_KEY = "last_comment_skip"


def note_skip(row: LeadSocialAccount, channel: str, reason: str, now: datetime) -> None:
    """The Page's last comment not taken, and why, for Settings → Connected apps."""
    config = dict(row.config or {})
    config[SKIP_KEY] = {"at": now.isoformat(), "channel": channel, "why": reason}
    row.config = config


def chat_key(channel: str, account_id: str, user_id: str) -> tuple[str, str, str]:
    return channel, account_id, user_id


async def known_people(db: AsyncSession, delivery: graph.Delivery) -> set[tuple[str, str, str]]:
    """People in this delivery Sales Xray already has a conversation with (so the webhook
    asks Meta for the names of new ones only)."""
    wanted = {chat_key(m.channel, m.account_id, m.user_id) for m in delivery.inbound}
    if not wanted:
        return set()
    rows = await db.execute(
        select(
            LeadSocialMessage.channel,
            LeadSocialAccount.page_id,
            LeadSocialAccount.ig_user_id,
            LeadSocialMessage.user_id,
        )
        .join(LeadSocialAccount, LeadSocialAccount.id == LeadSocialMessage.account_id)
        .where(LeadSocialMessage.user_id.in_([key[2] for key in wanted]))
        .distinct()
    )
    found: set[tuple[str, str, str]] = set()
    for channel, page_id, ig_id, user in rows.tuples():
        account_key = page_id if channel == "messenger" else (ig_id or "")
        found.add(chat_key(channel, account_key, user))
    return found & wanted


async def find_account(
    db: AsyncSession, channel: str, account_key: str
) -> LeadSocialAccount | None:
    column = LeadSocialAccount.page_id if channel == "messenger" else LeadSocialAccount.ig_user_id
    row: LeadSocialAccount | None = await db.scalar(
        select(LeadSocialAccount).where(column == account_key, LeadSocialAccount.status == "active")
    )
    return row


async def receive(
    db: AsyncSession,
    delivery: graph.Delivery,
    *,
    now: datetime,
    names: Mapping[tuple[str, str, str], str | None] | None = None,
    app_id: str | None = None,
) -> Received:
    """File one webhook delivery (the caller commits). ``names`` are the profile names
    the webhook already asked Meta for, outside any transaction."""
    out = Received()
    names = names or {}
    cache: dict[tuple[str, str], LeadSocialAccount | None] = {}

    async def find(channel: str, key: str) -> LeadSocialAccount | None:
        if (channel, key) not in cache:
            cache[(channel, key)] = await find_account(db, channel, key)
        row = cache[(channel, key)]
        return row if row is not None and account_config(row)[channel] else None

    for message in delivery.inbound:
        row = await find(message.channel, message.account_id)
        if row is None:
            continue
        name = names.get(chat_key(message.channel, message.account_id, message.user_id))
        lead, created = await lead_for(db, row, message.channel, message.user_id, name, now=now)
        inserted = await db.execute(
            insert(LeadSocialMessage)
            .values(
                id=uuid4(),
                tenant_id=row.tenant_id,
                account_id=row.id,
                lead_id=lead.id if lead else None,
                channel=message.channel,
                user_id=message.user_id,
                user_name=name,
                direction="in",
                mid=message.mid,
                kind=message.kind,
                body=message.body,
                status="received",
                meta_time=message.at,
                created_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=["mid"], index_where=LeadSocialMessage.mid.is_not(None)
            )
            .returning(LeadSocialMessage.id)
        )
        if inserted.first() is not None:
            out.messages += 1
            out.leads_created += created
            if lead is not None:
                lead.updated_at = now
    for echo in delivery.echoes:
        # Sales Xray's own sends are stored already; this keeps replies a person typed in
        # Meta's own inbox on the conversation too (no event: Sales Xray didn't send it).
        if app_id and echo.app_id == app_id:
            continue
        row = await find(echo.channel, echo.account_id)
        if row is None:
            continue
        lead_id = await _chat_lead(db, row, echo.channel, echo.user_id)
        await db.execute(
            insert(LeadSocialMessage)
            .values(
                id=uuid4(),
                tenant_id=row.tenant_id,
                account_id=row.id,
                lead_id=lead_id,
                channel=echo.channel,
                user_id=echo.user_id,
                direction="out",
                mid=echo.mid,
                kind="text" if echo.body else "unsupported",
                body=echo.body,
                status="sent",
                meta_time=echo.at,
                created_at=now,
                status_at=echo.at,
            )
            .on_conflict_do_nothing(
                index_elements=["mid"], index_where=LeadSocialMessage.mid.is_not(None)
            )
        )
    for seen in delivery.seen:
        row = await find(seen.channel, seen.account_id)
        if row is None:
            continue
        earlier = [name for name, rank in STATUS_ORDER.items() if rank < STATUS_ORDER[seen.status]]
        conditions = [
            LeadSocialMessage.account_id == row.id,
            LeadSocialMessage.channel == seen.channel,
            LeadSocialMessage.user_id == seen.user_id,
            LeadSocialMessage.direction == "out",
            LeadSocialMessage.status.in_(earlier),
        ]
        which: list[Any] = []
        if seen.mids:
            which.append(LeadSocialMessage.mid.in_(list(seen.mids)))
        if seen.until is not None:
            which.append(
                func.coalesce(LeadSocialMessage.meta_time, LeadSocialMessage.created_at)
                <= seen.until
            )
        if not which:
            continue
        result = await db.execute(
            update(LeadSocialMessage)
            .where(*conditions, or_(*which))
            .values(status=seen.status, status_at=seen.until or now)
        )
        out.statuses += int(getattr(result, "rowcount", 0) or 0)
    for comment in delivery.comments:
        row = await find(comment.channel, comment.account_id)
        if row is None:
            continue
        rules = account_config(row)["comments"]
        index = next(
            (
                number
                for number, rule in enumerate(rules)
                if rule.get("on") is not False
                and graph.matches(list(rule.get("keywords") or []), comment.text)
            ),
            None,
        )
        if index is None:
            # Only comments a rule asks for are kept.
            note_skip(row, comment.channel, "no_rule", now)
            out.skipped.append("no_rule")
            continue
        lead, created = await lead_for(
            db, row, comment.channel, comment.user_id, comment.user_name, now=now, comment=True
        )
        inserted = await db.execute(
            insert(LeadSocialMessage)
            .values(
                id=uuid4(),
                tenant_id=row.tenant_id,
                account_id=row.id,
                lead_id=lead.id if lead else None,
                channel=comment.channel,
                user_id=comment.user_id,
                user_name=comment.user_name,
                direction="in",
                comment_id=comment.comment_id,
                post_id=comment.post_id,
                kind="comment",
                body=comment.text,
                status="received",
                reply_state="pending",
                rule=index,
                meta_time=comment.at,
                created_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=["comment_id"], index_where=text("kind = 'comment'")
            )
            .returning(LeadSocialMessage.id)
        )
        if inserted.first() is not None:
            out.comments += 1
            out.leads_created += created
    for skip in delivery.skipped:
        row = await find(skip.channel, skip.account_id)
        if row is not None:
            note_skip(row, skip.channel, skip.reason, now)
        out.skipped.append(skip.reason)
    if delivery.unsent:
        result = await db.execute(
            update(LeadSocialMessage)
            .where(
                LeadSocialMessage.mid.in_(delivery.unsent),
                LeadSocialMessage.direction == "in",
                LeadSocialMessage.erased_at.is_(None),
            )
            .values(body=None, erased_at=now)
        )
        out.unsent += int(getattr(result, "rowcount", 0) or 0)
    return out


async def _chat_lead(
    db: AsyncSession, row: LeadSocialAccount, channel: str, user_id: str
) -> UUID | None:
    """The lead this conversation belongs to, if it is still in Lead Desk."""
    lead_id: UUID | None = await db.scalar(
        select(LeadSocialMessage.lead_id)
        .join(
            Lead,
            and_(
                Lead.tenant_id == LeadSocialMessage.tenant_id, Lead.id == LeadSocialMessage.lead_id
            ),
        )
        .where(
            LeadSocialMessage.account_id == row.id,
            LeadSocialMessage.channel == channel,
            LeadSocialMessage.user_id == user_id,
        )
        .order_by(LeadSocialMessage.created_at.desc())
        .limit(1)
    )
    return lead_id


def source_ref(row: LeadSocialAccount, channel: str, user_id: str) -> str:
    account = row.page_id if channel == "messenger" else (row.ig_user_id or row.page_id)
    return f"{'fb' if channel == 'messenger' else 'ig'}:{account}:{user_id}"


async def lead_for(
    db: AsyncSession,
    row: LeadSocialAccount,
    channel: str,
    user_id: str,
    name: str | None,
    *,
    now: datetime,
    comment: bool = False,
) -> tuple[Lead | None, bool]:
    """The lead this person is, or a new lead shared out by the organisation's rules."""
    known = await _chat_lead(db, row, channel, user_id)
    if known is not None:
        return await db.get(Lead, known), False
    ref = source_ref(row, channel, user_id)
    lead = await db.scalar(
        select(Lead).where(
            Lead.tenant_id == row.tenant_id, Lead.source == "webhook", Lead.source_ref == ref
        )
    )
    if lead is not None:
        return lead, False
    shown = name or (f"{LABELS[channel]} contact")
    record = {"name": shown, channel: user_id}
    if comment:
        record["came_from"] = "comment"
    lead, outcome = await _system(row, db, now).ingest(
        record, source="webhook", source_label=label(row, channel), source_ref=ref, actor=None
    )
    return lead, outcome == "created"


# ----- one lead's conversation ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Thread:
    account: LeadSocialAccount
    channel: str
    user_id: str
    messages: list[LeadSocialMessage]
    last_inbound: datetime | None


async def _lead(desk: LeadDesk, lead_id: UUID) -> Lead:
    lead = await desk.db.get(Lead, lead_id)
    if lead is None or lead.tenant_id != desk.tenant_id:
        raise DeskError(404, "That lead isn't here.")
    if not (desk.viewer.can_manage or lead.owner_person_id == desk.viewer.person_id):
        raise DeskError(403, "Only the lead's owner or a manager can see their messages.")
    return lead


def _last_inbound(messages: Sequence[LeadSocialMessage]) -> datetime | None:
    # A comment doesn't open the messaging window; a message does.
    return max(
        (
            m.meta_time or m.created_at
            for m in messages
            if m.direction == "in" and m.kind != "comment"
        ),
        default=None,
    )


async def threads(desk: LeadDesk, lead: Lead) -> list[Thread]:
    rows = list(
        (
            await desk.db.scalars(
                select(LeadSocialMessage)
                .where(
                    LeadSocialMessage.tenant_id == desk.tenant_id,
                    LeadSocialMessage.lead_id == lead.id,
                    LeadSocialMessage.erased_at.is_(None),
                )
                .order_by(LeadSocialMessage.created_at.desc())
                .limit(CONVERSATION_LIMIT)
            )
        ).all()
    )
    rows.reverse()
    by_chat: dict[tuple[UUID, str, str], list[LeadSocialMessage]] = {}
    for message in rows:
        by_chat.setdefault((message.account_id, message.channel, message.user_id), []).append(
            message
        )
    out: list[Thread] = []
    for (account_id, channel, user_id), messages in by_chat.items():
        row = await desk.db.get(LeadSocialAccount, account_id)
        if row is None:
            continue
        out.append(Thread(row, channel, user_id, messages, _last_inbound(messages)))
    out.sort(key=lambda thread: thread.messages[-1].created_at, reverse=True)
    return out


async def conversation(desk: LeadDesk, lead_id: UUID) -> tuple[Lead, list[Thread]]:
    lead = await _lead(desk, lead_id)
    return lead, await threads(desk, lead)


async def send(
    desk: LeadDesk,
    cfg: graph.SocialConfig,
    api: graph.Graph,
    lead_id: UUID,
    *,
    command_id: UUID,
    channel: str,
    account_id: UUID | None,
    body: str,
    human_agent: bool = False,
    auto: str | None = None,
    reply_to: LeadSocialMessage | None = None,
) -> LeadSocialMessage:
    """Send one message to a lead on Messenger or Instagram, inside Meta's rules."""
    seen = await desk.db.scalar(
        select(LeadEvent).where(
            LeadEvent.tenant_id == desk.tenant_id, LeadEvent.command_id == command_id
        )
    )
    if seen is not None:
        existing = await desk.db.get(
            LeadSocialMessage, UUID(str((seen.data or {}).get("message_id")))
        )
        if existing is not None:
            return existing
        raise DeskError(409, "That request was already used.")
    lead = await desk._lead(lead_id, lock=True) if auto else await _lead(desk, lead_id)
    text_value = body.strip()
    if not text_value:
        raise DeskError(422, "Write a message.")
    chats = [
        thread
        for thread in await threads(desk, lead)
        if thread.channel == channel and (account_id is None or thread.account.id == account_id)
    ]
    chat = next((t for t in chats if t.account.status == "active"), None)
    if chat is None:
        raise DeskError(
            409, f"This lead hasn't written to you on {LABELS.get(channel, channel)} yet."
        )
    rules = account_config(chat.account)
    tag: str | None = None
    if not graph.window_open(chat.last_inbound, desk.now):
        if auto or not human_agent:
            raise DeskError(
                409,
                "It's more than 24 hours since their last message, so Meta won't deliver this."
                + (" A person can still answer within 7 days." if rules["human_agent"] else ""),
            )
        if not rules["human_agent"] or not graph.human_agent_open(chat.last_inbound, desk.now):
            raise DeskError(409, "It's more than 7 days since their last message.")
        tag = "HUMAN_AGENT"
    message = LeadSocialMessage(
        id=uuid4(),
        tenant_id=desk.tenant_id,
        account_id=chat.account.id,
        lead_id=lead.id,
        channel=channel,
        user_id=chat.user_id,
        direction="out",
        kind="text",
        body=text_value[: graph.TEXT_LIMIT[channel]],
        status="queued",
        sent_by_person_id=None if auto else desk.viewer.person_id,
        auto=auto,
        tag=tag,
        created_at=desk.now,
    )
    desk.db.add(message)
    try:
        message.mid = await api.send(
            chat.account.page_id,
            page_token(cfg, chat.account),
            user_id=chat.user_id,
            text=message.body or "",
            channel=channel,
            human_agent=tag is not None,
        )
        message.status = "sent"
        message.status_at = desk.now
    except graph.SocialError as error:
        message.status = "failed"
        message.error_code = str(error.code) if error.code is not None else "refused"
        message.error_title = str(error)[:200]
    _record(desk, lead, message, command_id=command_id)
    await desk.db.flush()
    return message


def _record(
    desk: LeadDesk, lead: Lead, message: LeadSocialMessage, *, command_id: UUID | None
) -> None:
    desk._event(
        lead,
        "message",
        {
            "channel": message.channel,
            "via": "meta",
            "template": None,
            "message_id": str(message.id),
            "auto": message.auto,
            "human_agent": message.tag == "HUMAN_AGENT",
            "failed": message.status == "failed",
        },
        actor=message.sent_by_person_id,
        command_id=command_id,
    )
    lead.updated_at = desk.now


# ----- the inbox ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InboxThread:
    lead_id: UUID | None
    lead_name: str
    channel: str
    last_text: str | None
    last_at: datetime
    waiting: bool
    window_open: bool


_THREADS = """
    SELECT DISTINCT ON (m.account_id, m.channel, m.user_id)
           m.lead_id, m.channel, m.user_id, m.user_name, m.body, m.kind, m.direction,
           COALESCE(m.meta_time, m.created_at) AS at
    FROM lead_desk_social_messages m
    WHERE m.tenant_id = :tenant AND m.erased_at IS NULL AND m.created_at >= :since
    ORDER BY m.account_id, m.channel, m.user_id, COALESCE(m.meta_time, m.created_at) DESC,
             m.id DESC
"""

_LAST_IN = """
    SELECT m.account_id, m.channel, m.user_id, MAX(COALESCE(m.meta_time, m.created_at)) AS at
    FROM lead_desk_social_messages m
    WHERE m.tenant_id = :tenant AND m.direction = 'in' AND m.kind <> 'comment'
      AND m.created_at >= :since
    GROUP BY m.account_id, m.channel, m.user_id
"""


async def inbox(desk: LeadDesk, *, days: int = 30) -> list[InboxThread]:
    """Conversations of the last month, waiting ones first; a seller sees their own."""
    since = desk.now - timedelta(days=days)
    params = {"tenant": desk.tenant_id, "since": since}
    rows = (await desk.db.execute(text(_THREADS), params)).all()
    last_in = {
        (row.channel, row.user_id): row.at
        for row in (await desk.db.execute(text(_LAST_IN), params)).all()
    }
    leads = {
        lead.id: lead
        for lead in (
            await desk.db.scalars(
                select(Lead).where(
                    Lead.tenant_id == desk.tenant_id,
                    Lead.id.in_([row.lead_id for row in rows if row.lead_id]),
                )
            )
        ).all()
    }
    out: list[InboxThread] = []
    for row in rows:
        lead = leads.get(row.lead_id) if row.lead_id else None
        if not desk.viewer.can_manage and (
            lead is None or lead.owner_person_id != desk.viewer.person_id
        ):
            continue
        out.append(
            InboxThread(
                lead_id=lead.id if lead else None,
                lead_name=lead.name if lead else (row.user_name or LABELS[row.channel]),
                channel=row.channel,
                last_text=row.body or None,
                last_at=row.at,
                waiting=row.direction == "in",
                window_open=graph.window_open(last_in.get((row.channel, row.user_id)), desk.now),
            )
        )
    out.sort(key=lambda thread: (not thread.waiting, -thread.last_at.timestamp()))
    return out[:INBOX_LIMIT]


# ----- automations (the runner) -----------------------------------------------------------


async def comment_replies(
    db: AsyncSession, cfg: graph.SocialConfig, api: graph.Graph, *, now: datetime
) -> int:
    """One private reply (and the rule's public answer) to each comment a rule matched."""
    sent = 0
    pending = (
        await db.scalars(
            select(LeadSocialMessage)
            .where(LeadSocialMessage.reply_state == "pending", LeadSocialMessage.kind == "comment")
            .order_by(LeadSocialMessage.created_at)
            .limit(50)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for comment in pending:
        row = await db.get(LeadSocialAccount, comment.account_id)
        rules = account_config(row)["comments"] if row is not None else []
        rule = (
            rules[comment.rule] if comment.rule is not None and comment.rule < len(rules) else None
        )
        written = comment.meta_time or comment.created_at
        if (
            row is None
            or row.status != "active"
            or rule is None
            or now - written > graph.COMMENT_REPLY_WINDOW
            or comment.comment_id is None
        ):
            comment.reply_state = "skipped"
            continue
        words = graph.fill(str(rule["reply"]), comment.user_name)
        reply = LeadSocialMessage(
            id=uuid4(),
            tenant_id=comment.tenant_id,
            account_id=row.id,
            lead_id=comment.lead_id,
            channel=comment.channel,
            user_id=comment.user_id,
            user_name=comment.user_name,
            direction="out",
            comment_id=comment.comment_id,
            kind="text",
            body=words[: graph.TEXT_LIMIT[comment.channel]],
            status="queued",
            auto="comment_reply",
            created_at=now,
        )
        db.add(reply)
        token = page_token(cfg, row)
        try:
            mid, recipient = await api.private_reply(
                row.page_id,
                token,
                comment_id=comment.comment_id,
                text=reply.body or "",
                channel=comment.channel,
            )
            reply.mid = mid
            # Their messaging id: their answer to this message comes in under it.
            reply.user_id = recipient or comment.user_id
            reply.status = "sent"
            reply.status_at = now
            comment.reply_state = "replied"
            sent += 1
        except graph.SocialError as error:
            reply.status = "failed"
            reply.error_code = str(error.code) if error.code is not None else "refused"
            reply.error_title = str(error)[:200]
            comment.reply_state = "failed"
            comment.error_title = str(error)[:200]
        public = rule.get("public_reply")
        if public and reply.status == "sent":
            try:
                await api.public_reply(
                    token,
                    comment_id=comment.comment_id,
                    text=graph.fill(str(public), comment.user_name),
                    channel=comment.channel,
                )
            except graph.SocialError as error:
                comment.error_title = f"Public answer: {error}"[:200]
        if comment.lead_id is not None:
            lead = await db.get(Lead, comment.lead_id)
            if lead is not None:
                _record(_system(row, db, now), lead, reply, command_id=None)
        await db.flush()
    return sent


async def _auto_send(
    db: AsyncSession,
    cfg: graph.SocialConfig,
    api: graph.Graph,
    row: LeadSocialAccount,
    message: LeadSocialMessage,
    words: str,
    auto: str,
    now: datetime,
) -> bool:
    if message.lead_id is None:
        return False
    try:
        reply = await send(
            _system(row, db, now),
            cfg,
            api,
            message.lead_id,
            command_id=uuid4(),
            channel=message.channel,
            account_id=row.id,
            body=graph.fill(words, message.user_name),
            auto=auto,
        )
    except DeskError:
        return False
    return reply.status == "sent"


def _first_contact() -> Any:
    earlier = LeadSocialMessage.__table__.alias("earlier")
    return ~exists().where(
        earlier.c.account_id == LeadSocialMessage.account_id,
        earlier.c.channel == LeadSocialMessage.channel,
        earlier.c.user_id == LeadSocialMessage.user_id,
        or_(
            earlier.c.direction == "out",
            and_(earlier.c.kind != "comment", earlier.c.created_at < LeadSocialMessage.created_at),
        ),
    )


async def first_replies(
    db: AsyncSession, cfg: graph.SocialConfig, api: graph.Graph, *, now: datetime
) -> int:
    """An instant first reply to someone writing to the Page for the first time."""
    sent = 0
    for row in (
        await db.scalars(select(LeadSocialAccount).where(LeadSocialAccount.status == "active"))
    ).all():
        rule = account_config(row)["first_reply"]
        if not (rule["on"] and rule["text"]):
            continue
        waiting = (
            await db.scalars(
                select(LeadSocialMessage)
                .where(
                    LeadSocialMessage.account_id == row.id,
                    LeadSocialMessage.direction == "in",
                    LeadSocialMessage.kind != "comment",
                    LeadSocialMessage.created_at >= now - FIRST_REPLY_WITHIN,
                    _first_contact(),
                )
                .order_by(LeadSocialMessage.created_at)
                .limit(50)
            )
        ).all()
        for message in waiting:
            sent += await _auto_send(db, cfg, api, row, message, rule["text"], "first_reply", now)
    return sent


async def out_of_hours_replies(
    db: AsyncSession, cfg: graph.SocialConfig, api: graph.Graph, *, now: datetime
) -> int:
    """A reply to messages that arrive outside work hours, at most once in 12 hours."""
    sent = 0
    for row in (
        await db.scalars(select(LeadSocialAccount).where(LeadSocialAccount.status == "active"))
    ).all():
        rule = account_config(row)["out_of_hours"]
        if not (rule["on"] and rule["text"]):
            continue
        settings = await db.get(LeadDeskSettings, row.tenant_id)
        hours = work_hours.parse((settings.config if settings else None) or {})
        if hours is None or work_hours.inside(hours, now):
            continue
        waiting = (
            await db.scalars(
                select(LeadSocialMessage)
                .where(
                    LeadSocialMessage.account_id == row.id,
                    LeadSocialMessage.direction == "in",
                    LeadSocialMessage.kind != "comment",
                    LeadSocialMessage.created_at >= now - timedelta(minutes=30),
                    LeadSocialMessage.lead_id.is_not(None),
                )
                .order_by(LeadSocialMessage.created_at)
                .limit(50)
            )
        ).all()
        done: set[tuple[str, str]] = set()
        for message in waiting:
            key = (message.channel, message.user_id)
            if key in done:
                continue
            done.add(key)
            recent = await db.scalar(
                select(func.count())
                .select_from(LeadSocialMessage)
                .where(
                    LeadSocialMessage.account_id == row.id,
                    LeadSocialMessage.channel == message.channel,
                    LeadSocialMessage.user_id == message.user_id,
                    LeadSocialMessage.direction == "out",
                    or_(
                        LeadSocialMessage.auto == "out_of_hours",
                        LeadSocialMessage.created_at >= message.created_at,
                    ),
                    LeadSocialMessage.created_at >= now - OUT_OF_HOURS_EVERY,
                )
            )
            if recent:
                continue
            sent += await _auto_send(db, cfg, api, row, message, rule["text"], "out_of_hours", now)
    return sent


_GONE = """
    UPDATE lead_desk_social_messages m SET body = NULL, user_name = NULL, erased_at = :now
    WHERE m.id IN (
      SELECT x.id FROM lead_desk_social_messages x
      WHERE x.erased_at IS NULL AND x.lead_id IS NOT NULL
        AND NOT EXISTS (
          SELECT 1 FROM lead_desk_leads l WHERE l.tenant_id = x.tenant_id AND l.id = x.lead_id
        )
      LIMIT 500
    )
"""


async def erasure_sweep(db: AsyncSession, now: datetime) -> int:
    """A lead that leaves Lead Desk takes its Messenger and Instagram words with it."""
    result = await db.execute(text(_GONE), {"now": now})
    return int(getattr(result, "rowcount", 0) or 0)
