"""The outreach ingest API (v1.95, owner 22 Nov 2026: "every person we contact is a lead, every
message we send them is tracked, so we never feel spammy"; spec
boards/sx-redesign/review/v195-outreach-log-spec.md §3; lead_desk/outreach.py).

Tools outside Sales X-Ray (sx-engage, the tester auto-replies, the owner's own WhatsApp and
Gmail on the Mac) log what they send here and ask the same guard the app's send buttons ask:

- POST   /outreach/check               the guard for one recipient before a send; ``hold``
                                       also reserves the touch for 15 minutes (outreach:write)
- POST   /outreach/touches             log one touch sent (or failed): idempotent, matches or
                                       makes the lead, completes a reservation (outreach:write)
- DELETE /outreach/reservations/{id}   release a reservation that was not sent (outreach:write)
- POST   /outreach/statuses            up to 100 delivery updates, forward only (outreach:write)
- POST   /outreach/replies             one reply or first message: links to the touch it
                                       answers, may say STOP, opens the 24-hour window
                                       (outreach:write)
- POST   /outreach/opt-outs            record a STOP (outreach:write)
- GET    /outreach/opt-outs?since=     the workspace's STOPs, so every engine honours one said
                                       anywhere (outreach:read)
- GET    /outreach/touches?phone=|email=|lead_id=&since=&cursor=
                                       one recipient's touches (outreach:read)

Auth: an organisation API key (``sxk_``) with the scope; a connected app is refused
(``org_key_only``). Every write names a ``sender``: a sender of this workspace bound to this
very key (``sender_not_bound`` otherwise, also for another workspace's sender), active
(``sender_paused``) and allowed the channel (``channel_not_allowed``). A key says a touch came
from a person only through a person's own tool an owner or admin made for that person.

Idempotency: the provider's message id (provider, chat, id), else the sender's own
``client_ref``; a call with neither is ``needs_id``. The same key with the same body answers
200 ``duplicate``; with another recipient or content 409 ``idempotency_mismatch``; two at once,
the unique index decides and the loser answers the winner's touch.

Leads: the phone in E.164 (the workspace's default country), else the email; a merged lead is
its survivor; a teammate or a "Never a lead" contact is ``ignored: internal`` and nothing is
stored. With ``lead.create`` (or the sender's default) a new lead is made by the desk's own
intake, its source label the sender's, up to 3 tags by name.

Errors are ``{"error": {"code", "message"}}``; nothing here echoes a phone, email or words.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal
from uuid import UUID, uuid4, uuid5

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError

from ac_platform.http.rate_limits import InMemoryTokenBucketLimiter, RateLimitRule
from ac_platform.http.routes import RouteContext
from ac_platform.integrations.api_http import PRIVATE, ApiError, Reader, make_opener
from ac_platform.lead_desk import outreach
from ac_platform.lead_desk import tags as lead_tags
from ac_platform.lead_desk.capture import first_email, normalise_phone
from ac_platform.lead_desk.contracts import OutreachGuard
from ac_platform.lead_desk.errors import DeskError
from ac_platform.lead_desk.models import (
    Lead,
    LeadEvent,
    LeadOutreachSender,
    LeadTouch,
    LeadTouchReply,
)
from ac_platform.lead_desk.store import LeadDesk

WRITE: Final = "outreach:write"
READ: Final = "outreach:read"
# 600 a minute per key (spec §3.1), on top of the plan's own per-key limit.
RULE: Final = RateLimitRule(
    name="outreach-api-key",
    method="*",
    path=re.compile(r"^/v1/api/outreach"),
    capacity=600,
    refill_seconds=60.0,
)
AHEAD: Final = timedelta(minutes=5)
SEEN_EVERY: Final = timedelta(minutes=1)
PAGE: Final = 100
OPT_OUT_PAGE: Final = 1000
_TAGS: Final = UUID("5b0f2a66-91c7-4e3c-9a43-77f1d2a0c5e1")
_JID: Final = re.compile(r"^\+?(\d{6,20})@(s\.whatsapp\.net|c\.us)$")
Channel = Literal[
    "whatsapp", "sms", "email", "call", "messenger", "instagram", "in_person", "other"
]
Provider = Literal["meta_cloud", "wa_linked", "gmail", "smtp", "pulse", "phone", "other"]
SentStatus = Literal["sent", "delivered", "read", "failed"]
_LIMITER: list[InMemoryTokenBucketLimiter] = []


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class To(_Body):
    phone: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=320)
    name: str | None = Field(default=None, max_length=200)


class By(_Body):
    automation: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    person: Literal["self"] | None = None


class Attachment(_Body):
    kind: Literal["image", "video", "document", "audio", "quote"]
    name: str = Field(max_length=200)
    bytes: int | None = Field(default=None, ge=0)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class Content(_Body):
    kind: Literal["text", "template", "file", "quote", "link", "call", "voice"] = "text"
    summary: str | None = Field(default=None, max_length=4000)
    template: str | None = Field(default=None, max_length=512)
    attachment: Attachment | None = None


class LeadChoice(_Body):
    create: bool | None = None
    tags: list[str] = Field(default_factory=list, max_length=3)
    side: Literal["live", "cold"] | None = None
    name: str | None = Field(default=None, max_length=200)


class CheckBody(_Body):
    sender: str = Field(max_length=40)
    to: To
    channel: Channel = "whatsapp"
    hold: bool = False
    client_ref: str | None = Field(default=None, min_length=1, max_length=120)
    in_reply_to: str | None = Field(default=None, max_length=200)


class TouchBody(_Body):
    sender: str = Field(max_length=40)
    client_ref: str | None = Field(default=None, min_length=1, max_length=120)
    reservation_id: UUID | None = None
    to: To
    channel: Channel = "whatsapp"
    provider: Provider | None = None
    provider_message_id: str | None = Field(default=None, min_length=1, max_length=200)
    provider_chat_id: str | None = Field(default=None, max_length=80)
    sent_at: datetime
    by: By | None = None
    content: Content = Field(default_factory=Content)
    status: SentStatus = "sent"
    error_code: str | None = Field(default=None, max_length=32)
    in_reply_to: str | None = Field(default=None, max_length=200)
    lead: LeadChoice | None = None


class StatusItem(_Body):
    provider: Provider
    provider_message_id: str = Field(min_length=1, max_length=200)
    provider_chat_id: str | None = Field(default=None, max_length=80)
    status: SentStatus
    at: datetime
    error_code: str | None = Field(default=None, max_length=32)


class StatusesBody(_Body):
    sender: str = Field(max_length=40)
    statuses: list[StatusItem] = Field(min_length=1, max_length=100)


class ReplyBody(_Body):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, populate_by_name=True)
    sender: str = Field(max_length=40)
    provider: Provider
    provider_message_id: str = Field(min_length=1, max_length=200)
    provider_chat_id: str | None = Field(default=None, max_length=80)
    channel: Channel = "whatsapp"
    from_: To = Field(alias="from")
    at: datetime
    kind: Literal["text", "image", "video", "audio", "document", "sticker", "reaction", "other"] = (
        "text"
    )
    excerpt: str | None = Field(default=None, max_length=4000)
    opt_out: bool = False
    in_reply_to: str | None = Field(default=None, max_length=200)
    lead: LeadChoice | None = None


class OptOutBody(_Body):
    sender: str = Field(max_length=40)
    to: To
    channel: Channel = "whatsapp"
    at: datetime | None = None


@dataclass(slots=True)
class Call:
    reader: Reader
    desk: LeadDesk
    sender: LeadOutreachSender
    config: dict[str, Any]
    rules: outreach.Rules

    @property
    def now(self) -> datetime:
        return self.desk.now

    @property
    def sender_type(self) -> outreach.Sender:
        return "person" if self.sender.kind == "person_tool" else "automation"


def _limiter() -> InMemoryTokenBucketLimiter:
    if not _LIMITER:
        _LIMITER.append(InMemoryTokenBucketLimiter())
    return _LIMITER[0]


async def _key_only(reader: Reader, scope: str) -> None:
    if reader.caller.reach != "organisation" or reader.key.prefix.startswith("app "):
        raise ApiError(
            403, "org_key_only", "Use an organisation API key for the outreach log, not an app."
        )
    reader.require(scope)
    allowed, retry, _ = await _limiter().consume(str(reader.key.key_id), RULE)
    if not allowed:
        raise ApiError(429, "rate_limited", "Too many requests.", retry_after=max(1, retry))


async def _open(reader: Reader, scope: str, sender_key: str, channel: str | None = None) -> Call:
    await _key_only(reader, scope)
    desk = reader._desk()
    sender = await reader.session.scalar(
        select(LeadOutreachSender).where(
            LeadOutreachSender.tenant_id == reader.key.tenant_id,
            LeadOutreachSender.key == sender_key,
            LeadOutreachSender.api_key_id == reader.key.key_id,
        )
    )
    if sender is None:
        raise ApiError(
            403, "sender_not_bound", "That sender isn't bound to this key in this workspace."
        )
    if sender.status != "active":
        raise ApiError(403, "sender_paused", "An owner or admin paused this sender.")
    if channel is not None and channel not in (sender.channels or ()):
        raise ApiError(403, "channel_not_allowed", "This sender may not use that channel.")
    if sender.last_seen_at is None or sender.last_seen_at < desk.now - SEEN_EVERY:
        sender.last_seen_at = desk.now
    _, config = await outreach._settings(reader.session, reader.key.tenant_id)
    return Call(reader, desk, sender, config, outreach.parse_rules(config))


def _moment(value: datetime, now: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ApiError(422, "bad_time", "Send times with their time zone, e.g. +05:30 or Z.")
    if value > now + AHEAD:
        raise ApiError(422, "bad_time", "That time is in the future.")
    return value.astimezone(UTC)


def _phone(call: Call, raw: str | None) -> str | None:
    if not raw:
        return None
    if "@lid" in raw:
        raise ApiError(422, "phone_needed", "A linked-WhatsApp @lid id needs the phone number.")
    jid = _JID.fullmatch(raw.strip())
    text = f"+{jid.group(1)}" if jid else raw
    found = normalise_phone(text, default_country=str(call.config.get("default_country") or "91"))
    if found is None:
        raise ApiError(422, "bad_phone", "That phone number can't be read.")
    return found


async def _match(call: Call, to: To) -> tuple[Lead | None, str | None, str | None]:
    """The lead: the phone first (E.164), then the email; a merged lead's survivor."""
    phone = _phone(call, to.phone)
    email = first_email(to.email) if to.email else None
    if to.email and email is None and phone is None:
        raise ApiError(422, "bad_email", "That email address can't be read.")
    if phone is None and email is None:
        raise ApiError(422, "phone_needed", "Send the phone number (or an email).")
    db, tenant = call.reader.session, call.reader.key.tenant_id
    lead: Lead | None = None
    if phone is not None:
        lead = await db.scalar(select(Lead).where(Lead.tenant_id == tenant, Lead.phone == phone))
    if lead is None and email is not None:
        lead = await db.scalar(
            select(Lead)
            .where(Lead.tenant_id == tenant, func.lower(Lead.email) == email)
            .order_by(
                Lead.binned_at.is_not(None),
                Lead.archived_at.is_not(None),
                Lead.merged_into_id.is_not(None),
                Lead.created_at.desc(),
            )
            .limit(1)
        )
    if lead is not None:
        lead = await call.desk._live(lead)
    return lead, phone, email


async def _internal(call: Call, phone: str | None, email: str | None) -> bool:
    return await outreach.internal(
        call.reader.session,
        call.reader.key.tenant_id,
        call.rules,
        call.config,
        phone=phone,
        email=email,
    )


async def _create(
    call: Call, choice: LeadChoice | None, to: To, phone: str | None, email: str | None
) -> Lead | None:
    """A new lead for a recipient no lead matches, when the call or the sender says so."""
    defaults = dict(call.sender.lead_defaults or {})
    create = (
        choice.create
        if choice is not None and choice.create is not None
        else defaults.get("create", False)
    )
    if not create:
        return None
    side = (choice.side if choice is not None and choice.side else None) or defaults.get("side")
    name = (choice.name if choice is not None and choice.name else None) or to.name
    record = {
        key: value for key, value in {"name": name, "phone": phone, "email": email}.items() if value
    }
    try:
        lead, _ = await call.desk.ingest(
            record,
            source="webhook",
            source_label=call.sender.label,
            assign="rules" if defaults.get("assign") == "rules" else "none",
            actor=call.sender.person_id,
            side=side if side in ("live", "cold") else None,
            as_is=True,
        )
    except DeskError as error:
        raise ApiError(error.status, "lead_desk", str(error)) from None
    if lead is None:
        return None
    names = [
        " ".join(str(tag).split())[:32]
        for tag in (
            choice.tags if choice is not None and choice.tags else defaults.get("tags") or []
        )
        if str(tag).strip()
    ][:3]
    if names:
        try:
            made = [
                await lead_tags._make(
                    call.desk,
                    uuid5(_TAGS, f"{call.desk.tenant_id}:{name.lower()}"),
                    name,
                    None,
                )
                for name in names
            ]
            await lead_tags.apply(
                call.desk,
                [lead],
                add=list({tag.id: tag for tag in made}.values()),
                command_id=uuid5(_TAGS, f"lead:{lead.id}"),
                actor=call.sender.person_id,
                over="fit",
            )
        except DeskError:
            pass  # a full workspace of tags never loses the touch
    return lead


def _person(call: Call, by: By | None) -> tuple[UUID | None, str | None]:
    """Who sent it: an automation's rule, or the person a person's tool speaks for."""
    if call.sender.kind == "person_tool":
        if by is not None and (by.automation is not None or by.person not in (None, "self")):
            raise ApiError(422, "bad_by", 'A person\'s tool sends as {"person": "self"} only.')
        return call.sender.person_id, None
    if by is not None and by.person is not None:
        raise ApiError(422, "bad_by", "An automation can't say a person sent it.")
    return None, by.automation if by is not None else None


def _guard_json(result: OutreachGuard) -> dict[str, Any]:
    return result.model_dump(mode="json")


def _touch_json(touch: LeadTouch) -> dict[str, Any]:
    return {
        "touch_id": str(touch.id),
        "lead_id": str(touch.lead_id),
        "channel": touch.channel,
        "content_kind": touch.content_kind,
        "initiated": touch.initiated,
        "sender_type": touch.sender_type,
        "sender_id": str(touch.sender_id) if touch.sender_id else None,
        "person_id": str(touch.person_id) if touch.person_id else None,
        "automation": touch.automation,
        "via": touch.via,
        "provider": touch.provider,
        "provider_message_id": touch.provider_message_id,
        "provider_chat_id": touch.provider_chat_id,
        "client_ref": touch.client_ref,
        "summary": touch.summary,
        "status": touch.status,
        "sent_at": touch.sent_at.isoformat(),
        "counted": touch.counted,
        "replied_at": touch.replied_at.isoformat() if touch.replied_at else None,
        "after_block": bool((touch.guard or {}).get("after_block")),
    }


async def _after(call: Call, lead: Lead, channel: str) -> OutreachGuard:
    result, _, _ = await outreach.check_lead(
        call.reader.session, call.reader.key.tenant_id, lead, channel, call.sender_type, call.now
    )
    return result


# ----- check and reserve ------------------------------------------------------------------


async def check(reader: Reader, body: CheckBody) -> dict[str, Any]:
    call = await _open(reader, WRITE, body.sender, body.channel)
    lead, phone, email = await _match(call, body.to)
    if await _internal(call, phone, email):
        return {"ignored": "internal", "verdict": "ok", "lead_id": None}
    if lead is None:
        empty = outreach.guard(
            outreach.Facts(),
            channel=body.channel,
            sender=call.sender_type,
            rules=call.rules,
            window=outreach.window_for(call.rules, call.config),
            now=call.now,
        )
        return _guard_json(
            empty.model_copy(
                update={"would_create": bool((call.sender.lead_defaults or {}).get("create"))}
            )
        )
    # One check at a time per lead: two engines at the limit never both pass.
    lead = await reader.session.scalar(select(Lead).where(Lead.id == lead.id).with_for_update())
    assert lead is not None
    if body.hold and body.client_ref is not None:
        held = await reader.session.scalar(
            select(LeadTouch).where(
                LeadTouch.tenant_id == lead.tenant_id,
                LeadTouch.sender_id == call.sender.id,
                LeadTouch.client_ref == body.client_ref,
            )
        )
        if held is not None:
            if held.status != "queued":
                raise ApiError(409, "reservation_used", "That client_ref was sent already.")
            if held.expires_at is not None and held.expires_at > call.now:
                result = await _after(call, lead, body.channel)
                return _guard_json(result.model_copy(update={"reservation_id": held.id}))
            held.status, held.expires_at, held.counted = "expired", None, False
            held.client_ref = None
            await reader.session.flush()
    result = await _after(call, lead, body.channel)
    passes = result.verdict == "ok" or (result.verdict == "warn" and call.sender_type == "person")
    if not body.hold or not passes:
        return _guard_json(result)
    reservation = await outreach.record_touch(
        call.desk,
        lead,
        channel=body.channel,
        content_kind="text",
        via="api",
        sender_type=call.sender_type,
        person_id=call.sender.person_id,
        sender=call.sender,
        client_ref=body.client_ref,
        result=result,
        reserve=True,
    )
    return _guard_json(result.model_copy(update={"reservation_id": reservation.id}))


async def release(reader: Reader, reservation_id: UUID) -> dict[str, Any]:
    await _key_only(reader, WRITE)
    row = await reader.session.scalar(
        select(LeadTouch)
        .join(
            LeadOutreachSender,
            and_(
                LeadOutreachSender.tenant_id == LeadTouch.tenant_id,
                LeadOutreachSender.id == LeadTouch.sender_id,
            ),
        )
        .where(
            LeadTouch.tenant_id == reader.key.tenant_id,
            LeadTouch.id == reservation_id,
            LeadOutreachSender.api_key_id == reader.key.key_id,
        )
        .with_for_update(of=LeadTouch)
    )
    if row is None:
        raise ApiError(404, "reservation_not_found", "No such reservation from this key.")
    if row.status != "queued":
        if row.status == "expired":
            return {"reservation_id": str(row.id), "released": True}
        raise ApiError(409, "reservation_used", "That reservation was sent already.")
    now = datetime.now(UTC)
    row.status, row.expires_at, row.counted = "expired", None, False
    row.status_at, row.updated_at = now, now
    row.guard = {**(row.guard or {}), "released": True}
    return {"reservation_id": str(row.id), "released": True}


# ----- touches ------------------------------------------------------------------------------


def _request_sha(body: TouchBody) -> str:
    return outreach.body_sha256(
        body.model_dump(
            mode="json", exclude={"status", "reservation_id", "error_code", "sent_at", "lead"}
        )
    )


async def _existing(call: Call, body: TouchBody) -> LeadTouch | None:
    db, tenant = call.reader.session, call.reader.key.tenant_id
    found: LeadTouch | None
    if body.provider_message_id is not None:
        found = await db.scalar(
            select(LeadTouch).where(
                LeadTouch.tenant_id == tenant,
                LeadTouch.provider == body.provider,
                func.coalesce(LeadTouch.provider_chat_id, "") == (body.provider_chat_id or ""),
                LeadTouch.provider_message_id == body.provider_message_id,
            )
        )
        if found is not None:
            return found
    if body.client_ref is not None:
        found = await db.scalar(
            select(LeadTouch).where(
                LeadTouch.tenant_id == tenant,
                LeadTouch.sender_id == call.sender.id,
                LeadTouch.client_ref == body.client_ref,
            )
        )
        if found is not None:
            return found
    return None


async def _reservation(call: Call, body: TouchBody, found: LeadTouch | None) -> LeadTouch | None:
    if found is not None and found.status == "queued":
        if body.reservation_id is not None and body.reservation_id != found.id:
            raise ApiError(409, "idempotency_mismatch", "That client_ref has another reservation.")
        return found
    if body.reservation_id is None:
        return None
    row = await call.reader.session.scalar(
        select(LeadTouch)
        .where(
            LeadTouch.tenant_id == call.reader.key.tenant_id,
            LeadTouch.id == body.reservation_id,
            LeadTouch.sender_id == call.sender.id,
        )
        .with_for_update()
    )
    if row is None:
        raise ApiError(404, "reservation_not_found", "No such reservation from this sender.")
    if row.status != "queued" and found is None:
        if row.status == "expired":
            return None  # it lapsed: this send is logged as a touch of its own
        raise ApiError(409, "reservation_used", "That reservation was sent already.")
    return row if row.status == "queued" else None


def _duplicate(call: Call, touch: LeadTouch, sha: str, body: TouchBody) -> dict[str, Any]:
    if touch.sender_id != call.sender.id or (
        touch.request_sha256 is not None and touch.request_sha256 != sha
    ):
        raise ApiError(
            409,
            "idempotency_mismatch",
            "That message id was logged already with another recipient or content.",
        )
    outreach.apply_status(
        touch, body.status, _moment(body.sent_at, call.now), body.error_code, call.now
    )
    return {
        "touch_id": str(touch.id),
        "lead_id": str(touch.lead_id),
        "lead_created": False,
        "duplicate": True,
        "counted": touch.counted,
    }


async def log_touch(reader: Reader, body: TouchBody) -> tuple[dict[str, Any], int]:
    call = await _open(reader, WRITE, body.sender, body.channel)
    sent_at = _moment(body.sent_at, call.now)
    if body.content.summary is not None and len(body.content.summary) > 280:
        raise ApiError(422, "summary_too_long", "Keep the summary to 280 characters.")
    if body.provider_message_id is None and body.client_ref is None:
        raise ApiError(422, "needs_id", "Send provider_message_id, or your own client_ref.")
    if body.provider_message_id is not None and body.provider is None:
        raise ApiError(422, "needs_id", "Say which provider the message id is from.")
    person_id, automation = _person(call, body.by)
    sha = _request_sha(body)
    found = await _existing(call, body)
    if found is not None and found.status != "queued":
        return _duplicate(call, found, sha, body), 200
    reservation = await _reservation(call, body, found)
    lead, phone, email = await _match(call, body.to)
    if await _internal(call, phone, email):
        return {"ignored": "internal", "stored": False}, 200
    created = False
    if reservation is not None:
        if lead is not None and lead.id != reservation.lead_id:
            raise ApiError(409, "idempotency_mismatch", "That reservation is for someone else.")
        lead = await call.desk._lead(reservation.lead_id) if lead is None else lead
    if lead is None:
        lead = await _create(call, body.lead, body.to, phone, email)
        created = lead is not None
        if lead is None:
            return {"lead_id": None, "stored": False}, 200
    attachment = body.content.attachment.model_dump() if body.content.attachment else None
    event_data = {
        "sender": call.sender.key,
        "sender_label": call.sender.label,
        **({"auto": automation} if automation else {}),
    }
    if reservation is not None:
        touch = await _complete(
            call,
            lead,
            reservation,
            body,
            sent_at,
            sha,
            person_id,
            automation,
            attachment,
            event_data,
        )
    else:
        try:
            async with reader.session.begin_nested():
                touch = await outreach.record_touch(
                    call.desk,
                    lead,
                    channel=body.channel,
                    content_kind=body.content.kind,
                    via="api",
                    sender_type=call.sender_type,
                    person_id=person_id,
                    sender=call.sender,
                    automation=automation,
                    provider=body.provider,
                    provider_message_id=body.provider_message_id,
                    provider_chat_id=body.provider_chat_id,
                    client_ref=body.client_ref,
                    summary=body.content.summary,
                    template_name=body.content.template,
                    attachment=attachment,
                    status=body.status,
                    sent_at=sent_at,
                    request_sha256=sha,
                    error_code=body.error_code,
                    event_data=event_data,
                )
        except IntegrityError:
            # Another call with the same id won the race: answer as its duplicate.
            winner = await _existing(call, body)
            if winner is None:
                raise
            return _duplicate(call, winner, sha, body), 200
    return {
        "touch_id": str(touch.id),
        "lead_id": str(lead.id),
        "lead_created": created,
        "duplicate": False,
        "counted": touch.counted,
        "after_block": bool((touch.guard or {}).get("after_block")),
        "guard": _guard_json(await _after(call, lead, body.channel)),
    }, 201


async def _complete(
    call: Call,
    lead: Lead,
    touch: LeadTouch,
    body: TouchBody,
    sent_at: datetime,
    sha: str,
    person_id: UUID | None,
    automation: str | None,
    attachment: dict[str, Any] | None,
    event_data: dict[str, Any],
) -> LeadTouch:
    """A reservation becomes the touch it held a place for (its guard verdict stays)."""
    desk = call.desk
    touch.status, touch.expires_at = body.status, None
    touch.status_at = sent_at
    touch.sent_at = sent_at
    touch.content_kind = body.content.kind
    touch.person_id = person_id if touch.sender_type == "person" else None
    touch.automation = automation
    touch.provider = body.provider
    touch.provider_message_id = body.provider_message_id
    touch.provider_chat_id = body.provider_chat_id
    touch.client_ref = body.client_ref or touch.client_ref
    touch.summary = outreach._summary(body.content.summary)
    touch.template_name = body.content.template
    touch.attachment = attachment
    touch.request_sha256 = sha
    touch.error_code = body.error_code if body.status == "failed" else None
    touch.counted = bool((touch.guard or {}).get("counts")) and body.status != "failed"
    touch.updated_at = desk.now
    line = outreach._event_for(
        desk,
        lead,
        touch.channel,
        actor=touch.person_id,
        data={"via": "api", "touch_id": str(touch.id), **event_data},
        at=sent_at,
    )
    touch.event_id = line.id
    try:
        async with call.reader.session.begin_nested():
            await call.reader.session.flush()
    except IntegrityError:
        raise ApiError(
            409, "idempotency_mismatch", "That message id was logged already on another touch."
        ) from None
    if touch.sender_type == "person" and body.status != "failed":
        lead.first_contact_at = lead.first_contact_at or sent_at
    lead.updated_at = desk.now
    return touch


# ----- statuses, replies, opt-outs ----------------------------------------------------------


async def statuses(reader: Reader, body: StatusesBody) -> dict[str, Any]:
    call = await _open(reader, WRITE, body.sender)
    updated = ignored = unknown = 0
    for item in body.statuses:
        at = _moment(item.at, call.now)
        touch = await reader.session.scalar(
            select(LeadTouch)
            .where(
                LeadTouch.tenant_id == reader.key.tenant_id,
                LeadTouch.sender_id == call.sender.id,
                LeadTouch.provider == item.provider,
                func.coalesce(LeadTouch.provider_chat_id, "") == (item.provider_chat_id or ""),
                LeadTouch.provider_message_id == item.provider_message_id,
            )
            .with_for_update()
        )
        if touch is None:
            unknown += 1
        elif outreach.apply_status(touch, item.status, at, item.error_code, call.now):
            updated += 1
        else:
            ignored += 1
    return {"updated": updated, "ignored": ignored, "unknown": unknown}


async def reply(reader: Reader, body: ReplyBody) -> tuple[dict[str, Any], int]:
    call = await _open(reader, WRITE, body.sender, body.channel)
    at = _moment(body.at, call.now)
    if body.kind == "reaction":
        return {"ignored": "reaction", "stored": False}, 200
    db, tenant = reader.session, reader.key.tenant_id
    seen = await db.scalar(
        select(LeadTouchReply).where(
            LeadTouchReply.tenant_id == tenant,
            LeadTouchReply.provider == body.provider,
            func.coalesce(LeadTouchReply.provider_chat_id, "") == (body.provider_chat_id or ""),
            LeadTouchReply.provider_message_id == body.provider_message_id,
        )
    )
    if seen is not None:
        return {
            "reply_id": str(seen.id),
            "lead_id": str(seen.lead_id),
            "lead_created": False,
            "duplicate": True,
            "touch_id": str(seen.touch_id) if seen.touch_id else None,
            "opted_out": seen.opt_out,
        }, 200
    lead, phone, email = await _match(call, body.from_)
    if await _internal(call, phone, email):
        return {"ignored": "internal", "stored": False}, 200
    created = False
    if lead is None:
        lead = await _create(call, body.lead, body.from_, phone, email)
        created = lead is not None
        if lead is None:
            return {"lead_id": None, "stored": False}, 200
    row = LeadTouchReply(
        id=uuid4(),
        tenant_id=tenant,
        lead_id=lead.id,
        touch_id=None,
        sender_id=call.sender.id,
        channel=body.channel,
        provider=body.provider,
        provider_message_id=body.provider_message_id,
        provider_chat_id=body.provider_chat_id,
        kind=body.kind,
        # The lead's own words: kept only when the workspace turned "Keep reply words" on.
        excerpt=(body.excerpt or "")[:280] or None if call.rules.keep_reply_words else None,
        opt_out=body.opt_out,
        received_at=at,
        created_at=call.now,
    )
    touch = await outreach.link_reply(
        db,
        tenant,
        lead.id,
        body.channel,
        at,
        {"table": "reply", "id": str(row.id)},
        in_reply_to=(body.provider, body.provider_chat_id, body.in_reply_to)
        if body.in_reply_to
        else None,
    )
    row.touch_id = touch.id if touch is not None else None
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        winner = await db.scalar(
            select(LeadTouchReply).where(
                LeadTouchReply.tenant_id == tenant,
                LeadTouchReply.provider == body.provider,
                func.coalesce(LeadTouchReply.provider_chat_id, "") == (body.provider_chat_id or ""),
                LeadTouchReply.provider_message_id == body.provider_message_id,
            )
        )
        if winner is None:
            raise
        return {
            "reply_id": str(winner.id),
            "lead_id": str(winner.lead_id),
            "lead_created": False,
            "duplicate": True,
            "touch_id": str(winner.touch_id) if winner.touch_id else None,
            "opted_out": winner.opt_out,
        }, 200
    opted = False
    if body.opt_out:
        opted = await outreach.record_opt_out(
            call.desk, lead, body.channel, f"Said stop ({call.sender.label})"
        )
    lead.updated_at = call.now
    return {
        "reply_id": str(row.id),
        "lead_id": str(lead.id),
        "lead_created": created,
        "duplicate": False,
        "touch_id": str(touch.id) if touch is not None else None,
        "opted_out": body.opt_out,
        "recorded_opt_out": opted,
    }, 201


async def opt_out(reader: Reader, body: OptOutBody) -> dict[str, Any]:
    call = await _open(reader, WRITE, body.sender, body.channel)
    if body.at is not None:
        _moment(body.at, call.now)
    lead, _, _ = await _match(call, body.to)
    if lead is None:
        return {"lead_id": None, "recorded": False}
    recorded = await outreach.record_opt_out(
        call.desk, lead, body.channel, f"Said stop ({call.sender.label})"
    )
    return {"lead_id": str(lead.id), "recorded": recorded, "channel": body.channel}


def _since(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise ApiError(422, "bad_time", "since is a time like 2026-11-23T10:00:00Z.") from None
    if at.tzinfo is None:
        raise ApiError(422, "bad_time", "Send times with their time zone, e.g. +05:30 or Z.")
    return at


async def opt_outs(reader: Reader, since: str | None) -> dict[str, Any]:
    await _key_only(reader, READ)
    after = _since(since)
    marker = or_(
        LeadEvent.data[outreach.WHATSAPP_OPT_IN].as_string() == "false",
        LeadEvent.data[outreach.OPT_OUT].as_string().is_not(None),
    )
    query = (
        select(LeadEvent, Lead.phone, Lead.email)
        .join(Lead, and_(Lead.tenant_id == LeadEvent.tenant_id, Lead.id == LeadEvent.lead_id))
        .where(LeadEvent.tenant_id == reader.key.tenant_id, LeadEvent.kind == "edited", marker)
        .order_by(LeadEvent.created_at, LeadEvent.id)
        .limit(OPT_OUT_PAGE)
    )
    if after is not None:
        query = query.where(LeadEvent.created_at > after)
    rows = (await reader.session.execute(query)).all()
    items = []
    for event, phone, email in rows:
        data = event.data or {}
        channel = (
            "whatsapp" if outreach.WHATSAPP_OPT_IN in data else str(data.get(outreach.OPT_OUT))
        )
        items.append(
            {
                "lead_id": str(event.lead_id),
                "channel": channel,
                "phone": phone,
                "email": email,
                "at": event.created_at.isoformat(),
            }
        )
    return {
        "opt_outs": items,
        "next_since": items[-1]["at"] if len(items) == OPT_OUT_PAGE else None,
    }


async def touches(
    reader: Reader,
    *,
    phone: str | None,
    email: str | None,
    lead_id: UUID | None,
    since: str | None,
    cursor: str | None,
) -> dict[str, Any]:
    await _key_only(reader, READ)
    db, tenant = reader.session, reader.key.tenant_id
    lead: Lead | None = None
    if lead_id is not None:
        lead = await db.scalar(select(Lead).where(Lead.tenant_id == tenant, Lead.id == lead_id))
    elif phone or email:
        _, config = await outreach._settings(db, tenant)
        probe = Call(
            reader, reader._desk(), LeadOutreachSender(), config, outreach.parse_rules(config)
        )
        lead, _, _ = await _match(probe, To(phone=phone, email=email))
    else:
        raise ApiError(422, "phone_needed", "Send lead_id, phone or email.")
    if lead is None:
        return {"lead_id": None, "touches": [], "next_cursor": None}
    query = select(LeadTouch).where(
        LeadTouch.tenant_id == tenant, LeadTouch.lead_id == lead.id, LeadTouch.status != "queued"
    )
    after = _since(since)
    if after is not None:
        query = query.where(LeadTouch.sent_at > after)
    try:
        before = outreach.parse_cursor(cursor)
    except DeskError:
        raise ApiError(422, "bad_cursor", "That cursor is wrong.") from None
    if before is not None:
        query = query.where(
            or_(
                LeadTouch.sent_at < before[0],
                and_(LeadTouch.sent_at == before[0], LeadTouch.id < before[1]),
            )
        )
    rows = (
        await db.scalars(
            query.order_by(LeadTouch.sent_at.desc(), LeadTouch.id.desc()).limit(PAGE + 1)
        )
    ).all()
    more = len(rows) > PAGE
    rows = rows[:PAGE]
    return {
        "lead_id": str(lead.id),
        "touches": [_touch_json(row) for row in rows],
        "next_cursor": outreach._cursor(rows[-1]) if more and rows else None,
    }


# ----- routes -------------------------------------------------------------------------------


def install_outreach_api(application: FastAPI, ctx: RouteContext) -> None:
    router = APIRouter(prefix="/v1/api/outreach", tags=["sales-xray-api"])
    open_reader = make_opener(ctx)

    def done(body: dict[str, Any], status: int = 200) -> JSONResponse:
        return JSONResponse(body, status_code=status, headers=PRIVATE)

    def desk_error(error: DeskError) -> ApiError:
        return ApiError(error.status, "lead_desk", str(error))

    @router.post("/check")
    async def check_route(body: CheckBody, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            try:
                return done(await check(reader, body))
            except DeskError as error:
                raise desk_error(error) from None

    @router.post("/touches")
    async def touch_route(body: TouchBody, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            try:
                return done(*await log_touch(reader, body))
            except DeskError as error:
                raise desk_error(error) from None

    @router.delete("/reservations/{reservation_id}")
    async def release_route(reservation_id: UUID, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await release(reader, reservation_id))

    @router.post("/statuses")
    async def statuses_route(body: StatusesBody, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await statuses(reader, body))

    @router.post("/replies")
    async def reply_route(body: ReplyBody, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            try:
                return done(*await reply(reader, body))
            except DeskError as error:
                raise desk_error(error) from None

    @router.post("/opt-outs")
    async def opt_out_route(body: OptOutBody, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await opt_out(reader, body))

    @router.get("/opt-outs")
    async def opt_outs_route(request: Request, since: str | None = None) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await opt_outs(reader, since))

    @router.get("/touches")
    async def touches_route(
        request: Request,
        phone: str | None = None,
        email: str | None = None,
        lead_id: UUID | None = None,
        since: str | None = None,
        cursor: str | None = None,
    ) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(
                await touches(
                    reader, phone=phone, email=email, lead_id=lead_id, since=since, cursor=cursor
                )
            )

    application.include_router(router)


__all__ = ["install_outreach_api"]
