"""The Sales Xray CRM's WhatsApp inbox: numbers, conversations, sending, templates.

- A message from someone new becomes a lead through ``LeadDesk.ingest`` (so the
  organisation's own allocation rules pick the seller); a message from a lead goes on
  that lead's conversation. Messages are stored once (Meta's message id).
- A seller (the lead's owner) or a manager replies. Free text only inside the 24-hour
  window; after it, an approved template, and only to someone who agreed to WhatsApp
  (they messaged the business, their lead form said yes, or the seller recorded their
  yes). Every send is a ``message`` event on the lead's history (never its text).
- Auto replies, per number: an instant first reply to a new ad lead whose form said
  yes to WhatsApp (an approved template with their first name), and a reply to a
  message that arrives outside work hours (inside the window, so plain text).

Message text is the customer's own data: it lives only in
``lead_desk_whatsapp_messages`` and is emptied when the lead leaves Lead Desk.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.lead_desk import hours as work_hours
from ac_platform.lead_desk.models import (
    Lead,
    LeadEvent,
    LeadWhatsAppMessage,
    LeadWhatsAppNumber,
    LeadWhatsAppTemplate,
)
from ac_platform.lead_desk.store import DeskError, LeadDesk, Viewer
from ac_platform.lead_desk.whatsapp import cloud
from ac_platform.partner_events.lead_events import consent_granted

OPT_IN: Final[str] = "whatsapp_opt_in"  # the lead event marker (kind "edited")
STATUS_ORDER: Final[dict[str, int]] = {"queued": 0, "sent": 1, "delivered": 2, "read": 3}
FIRST_REPLY_WITHIN: Final[timedelta] = timedelta(minutes=30)
OUT_OF_HOURS_EVERY: Final[timedelta] = timedelta(hours=12)
CONVERSATION_LIMIT: Final[int] = 200
INBOX_LIMIT: Final[int] = 100
DEFAULT_CONFIG: Final[dict[str, Any]] = {
    "first_reply": {"on": False, "template": None, "language": None, "consent_question": None},
    "out_of_hours": {"on": False, "text": None},
}


def number_config(number: LeadWhatsAppNumber) -> dict[str, Any]:
    raw = number.config if isinstance(number.config, dict) else {}
    return {
        "first_reply": {**DEFAULT_CONFIG["first_reply"], **(raw.get("first_reply") or {})},
        "out_of_hours": {**DEFAULT_CONFIG["out_of_hours"], **(raw.get("out_of_hours") or {})},
    }


# ----- numbers ---------------------------------------------------------------------------


async def numbers(
    db: AsyncSession, tenant_id: UUID, *, active: bool = True
) -> list[LeadWhatsAppNumber]:
    query = select(LeadWhatsAppNumber).where(LeadWhatsAppNumber.tenant_id == tenant_id)
    if active:
        query = query.where(LeadWhatsAppNumber.status == "active")
    return list((await db.scalars(query.order_by(LeadWhatsAppNumber.created_at))).all())


async def number(db: AsyncSession, tenant_id: UUID, number_id: UUID) -> LeadWhatsAppNumber:
    row = await db.get(LeadWhatsAppNumber, number_id)
    if row is None or row.tenant_id != tenant_id or row.status != "active":
        raise DeskError(404, "That WhatsApp number isn't connected here.")
    return row


def token(cfg: cloud.WhatsAppConfig, row: LeadWhatsAppNumber) -> str:
    return cloud.unseal(cfg, row.token, phone_number_id=row.phone_number_id, what="token")


async def connect(
    desk: LeadDesk,
    cfg: cloud.WhatsAppConfig,
    api: cloud.Cloud,
    *,
    code: str,
    waba_id: str,
    phone_number_id: str,
) -> LeadWhatsAppNumber:
    """Embedded Signup finished in the page: swap its code and keep the number."""
    desk._require_manager()
    if not (cloud.META_ID.fullmatch(waba_id) and cloud.META_ID.fullmatch(phone_number_id)):
        raise DeskError(422, "WhatsApp didn't say which number. Connect again.")
    business_token = await api.exchange(code)
    return await connect_number(
        desk, cfg, api, business_token, waba_id=waba_id, phone_number_id=phone_number_id
    )


async def connect_shared(
    desk: LeadDesk, cfg: cloud.WhatsAppConfig, api: cloud.Cloud, business_token: str
) -> list[LeadWhatsAppNumber]:
    """Embedded Signup came back to Sales Xray (the redirect flow): connect every number
    of every WhatsApp account the customer shared."""
    desk._require_manager()
    rows: list[LeadWhatsAppNumber] = []
    for waba_id in await api.shared_accounts(business_token):
        for phone_number_id in await api.phone_numbers(waba_id, business_token):
            rows.append(
                await connect_number(
                    desk,
                    cfg,
                    api,
                    business_token,
                    waba_id=waba_id,
                    phone_number_id=phone_number_id,
                )
            )
    return rows


async def connect_number(
    desk: LeadDesk,
    cfg: cloud.WhatsAppConfig,
    api: cloud.Cloud,
    business_token: str,
    *,
    waba_id: str,
    phone_number_id: str,
) -> LeadWhatsAppNumber:
    """Keep one number with its sealed token and a PIN we set; subscribe and register it."""
    elsewhere = await desk.db.scalar(
        select(LeadWhatsAppNumber.tenant_id).where(
            LeadWhatsAppNumber.phone_number_id == phone_number_id,
            LeadWhatsAppNumber.status == "active",
            LeadWhatsAppNumber.tenant_id != desk.tenant_id,
        )
    )
    if elsewhere is not None:
        raise DeskError(409, "This WhatsApp number is connected to another organisation.")
    facts = await api.number(phone_number_id, business_token)
    await api.subscribe(waba_id, business_token)
    pin = cloud.new_pin()
    await api.register(phone_number_id, business_token, pin)
    row = await desk.db.scalar(
        select(LeadWhatsAppNumber)
        .where(
            LeadWhatsAppNumber.tenant_id == desk.tenant_id,
            LeadWhatsAppNumber.phone_number_id == phone_number_id,
            LeadWhatsAppNumber.status == "active",
        )
        .with_for_update()
    )
    sealed = cloud.seal(cfg, business_token, phone_number_id=phone_number_id, what="token")
    sealed_pin = cloud.seal(cfg, pin, phone_number_id=phone_number_id, what="pin")
    if row is None:
        row = LeadWhatsAppNumber(
            id=uuid4(),
            tenant_id=desk.tenant_id,
            waba_id=waba_id,
            phone_number_id=phone_number_id,
            config={},
            status="active",
            connected_by_person_id=desk.viewer.person_id,
            created_at=desk.now,
            token=sealed,
        )
        desk.db.add(row)
    row.waba_id = waba_id
    row.token = sealed
    row.pin = sealed_pin
    row.display_number = facts["display_number"]
    row.verified_name = facts["verified_name"] or None
    row.quality = facts["quality"] or None
    row.updated_at = desk.now
    await desk.db.flush()
    return row


async def disconnect(desk: LeadDesk, number_id: UUID) -> None:
    desk._require_manager()
    row = await number(desk.db, desk.tenant_id, number_id)
    row.status = "disconnected"
    row.disconnected_at = desk.now
    row.updated_at = desk.now
    await desk.db.flush()


def save_auto_replies(
    row: LeadWhatsAppNumber, settings: Mapping[str, Any], approved: set[tuple[str, str]]
) -> None:
    """A manager's auto replies for one number; a first reply needs an approved template
    and the lead form's WhatsApp consent question."""
    first = dict(settings.get("first_reply") or {})
    late = dict(settings.get("out_of_hours") or {})
    if first.get("on"):
        pair = (str(first.get("template") or ""), str(first.get("language") or ""))
        if pair not in approved:
            raise DeskError(422, "Pick an approved template for the first reply.")
        question = str(first.get("consent_question") or "").strip()
        if not question:
            raise DeskError(
                422,
                "Name the lead form question where people agree to WhatsApp: the first "
                "reply goes only to those who said yes.",
            )
        first["consent_question"] = question[:200]
    text_value = str(late.get("text") or "").strip()
    if late.get("on") and not text_value:
        raise DeskError(422, "Write the reply for messages that arrive after hours.")
    late["text"] = text_value[:1000] or None
    row.config = {
        "first_reply": {
            "on": bool(first.get("on")),
            "template": first.get("template") or None,
            "language": first.get("language") or None,
            "consent_question": first.get("consent_question") or None,
        },
        "out_of_hours": {"on": bool(late.get("on")), "text": late["text"]},
    }


# ----- receiving -------------------------------------------------------------------------


@dataclass(slots=True)
class Received:
    messages: int = 0
    leads_created: int = 0
    statuses: int = 0
    templates: int = 0


async def receive(db: AsyncSession, delivery: cloud.Delivery, *, now: datetime) -> Received:
    """File one webhook delivery (the caller commits)."""
    out = Received()
    by_number: dict[str, LeadWhatsAppNumber | None] = {}

    async def find(phone_number_id: str) -> LeadWhatsAppNumber | None:
        if phone_number_id not in by_number:
            by_number[phone_number_id] = await db.scalar(
                select(LeadWhatsAppNumber).where(
                    LeadWhatsAppNumber.phone_number_id == phone_number_id,
                    LeadWhatsAppNumber.status == "active",
                )
            )
        return by_number[phone_number_id]

    for message in delivery.inbound:
        row = await find(message.phone_number_id)
        if row is None:
            continue
        lead, created = await lead_for(db, row, message, now=now)
        inserted = await db.execute(
            insert(LeadWhatsAppMessage)
            .values(
                id=uuid4(),
                tenant_id=row.tenant_id,
                number_id=row.id,
                lead_id=lead.id if lead else None,
                wa_id=message.wa_id,
                direction="in",
                wamid=message.wamid,
                kind=message.kind,
                body=message.body,
                media=message.media,
                status="received",
                meta_time=message.at,
                created_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=["wamid"], index_where=LeadWhatsAppMessage.wamid.is_not(None)
            )
            .returning(LeadWhatsAppMessage.id)
        )
        if inserted.first() is not None:
            out.messages += 1
            out.leads_created += created
            if lead is not None:
                lead.updated_at = now
    for status in delivery.statuses:
        rank = STATUS_ORDER.get(status.status)
        query = update(LeadWhatsAppMessage).where(
            LeadWhatsAppMessage.wamid == status.wamid, LeadWhatsAppMessage.direction == "out"
        )
        if status.status == "failed":
            query = query.values(
                status="failed",
                error_code=status.error_code,
                error_title=status.error_title,
                status_at=status.at,
            )
        else:
            later = [name for name, order in STATUS_ORDER.items() if order < (rank or 0)]
            query = query.where(LeadWhatsAppMessage.status.in_(later)).values(
                status=status.status, status_at=status.at
            )
        result = await db.execute(query)
        out.statuses += int(getattr(result, "rowcount", 0) or 0)
    for change in delivery.templates:
        result = await db.execute(
            update(LeadWhatsAppTemplate)
            .where(
                LeadWhatsAppTemplate.waba_id == change.waba_id,
                LeadWhatsAppTemplate.meta_id == change.meta_id,
            )
            .values(status=change.status, rejected_reason=change.reason, updated_at=now)
        )
        out.templates += int(getattr(result, "rowcount", 0) or 0)
    for display, rating in delivery.quality:
        await db.execute(
            update(LeadWhatsAppNumber)
            .where(
                LeadWhatsAppNumber.display_number == display,
                LeadWhatsAppNumber.status == "active",
            )
            .values(quality=rating, updated_at=now)
        )
    return out


async def lead_for(
    db: AsyncSession, row: LeadWhatsAppNumber, message: cloud.Inbound, *, now: datetime
) -> tuple[Lead | None, bool]:
    """The lead this person is, or a new lead shared out by the organisation's rules."""
    phone = cloud.e164(message.wa_id)
    lead = await db.scalar(select(Lead).where(Lead.tenant_id == row.tenant_id, Lead.phone == phone))
    if lead is not None:
        return lead, False
    desk = LeadDesk(
        db,
        Viewer(
            person_id=row.connected_by_person_id,
            tenant_id=row.tenant_id,
            role="system",
            name="WhatsApp",
        ),
        now=now,
    )
    record = {"name": message.profile_name or phone, "phone": phone}
    lead, outcome = await desk.ingest(
        record,
        source="webhook",
        source_label=f"WhatsApp · {row.display_number}"[:120],
        source_ref=f"wa:{message.wa_id}",
        actor=None,
    )
    return lead, outcome == "created"


# ----- one lead's conversation ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Conversation:
    lead: Lead
    messages: list[LeadWhatsAppMessage]
    last_inbound: datetime | None
    opted_in: bool
    opt_in_how: str | None
    numbers: list[LeadWhatsAppNumber]


async def _lead(desk: LeadDesk, lead_id: UUID) -> Lead:
    lead = await desk.db.get(Lead, lead_id)
    if lead is None or lead.tenant_id != desk.tenant_id:
        raise DeskError(404, "That lead isn't here.")
    if not (desk.viewer.can_manage or lead.owner_person_id == desk.viewer.person_id):
        raise DeskError(403, "Only the lead's owner or a manager can see their WhatsApp.")
    return lead


def _chat_filter(lead: Lead) -> Any:
    wa = cloud.wa_id(lead.phone)
    by_wa = LeadWhatsAppMessage.wa_id == wa if wa else LeadWhatsAppMessage.id.is_(None)
    return and_(
        LeadWhatsAppMessage.tenant_id == lead.tenant_id,
        or_(LeadWhatsAppMessage.lead_id == lead.id, by_wa),
        LeadWhatsAppMessage.erased_at.is_(None),
    )


async def opt_in_state(
    db: AsyncSession, lead: Lead, config: Mapping[str, Any] | None = None
) -> tuple[bool, str | None]:
    """Whether this person agreed to WhatsApp, and how. The latest recorded answer wins;
    a message from them, or a yes on their lead form, also counts."""
    marks = (
        await db.scalars(
            select(LeadEvent)
            .where(
                LeadEvent.tenant_id == lead.tenant_id,
                LeadEvent.lead_id == lead.id,
                LeadEvent.kind == "edited",
            )
            .order_by(LeadEvent.created_at.desc())
        )
    ).all()
    for mark in marks:
        data = mark.data if isinstance(mark.data, dict) else {}
        if isinstance(data.get(OPT_IN), bool):
            return data[OPT_IN], str(data.get("how") or "") or None
    wrote = await db.scalar(
        select(func.count())
        .select_from(LeadWhatsAppMessage)
        .where(_chat_filter(lead), LeadWhatsAppMessage.direction == "in")
    )
    if wrote:
        return True, "They messaged you on WhatsApp"
    question = (config or {}).get("consent_question") if config else None
    if question and form_said_yes(lead.payload, str(question)):
        return True, "Yes on their lead form"
    return False, None


def form_said_yes(payload: Any, question: str) -> bool:
    """Their lead form's answer to the organisation's WhatsApp consent question is yes."""
    folded = question.strip().casefold()
    answers: list[tuple[str, Any]] = []
    if isinstance(payload, Mapping):
        for item in payload.get("field_data") or []:
            if isinstance(item, Mapping) and isinstance(item.get("name"), str):
                values = item.get("values")
                answers.append(
                    (item["name"], values[0] if isinstance(values, list) and values else values)
                )
        answers.extend((key, value) for key, value in payload.items() if isinstance(key, str))
    for name, value in answers:
        if name.strip().casefold() == folded:
            return consent_granted(value) is True
    return False


async def conversation(desk: LeadDesk, lead_id: UUID) -> Conversation:
    lead = await _lead(desk, lead_id)
    messages = list(
        (
            await desk.db.scalars(
                select(LeadWhatsAppMessage)
                .where(_chat_filter(lead))
                .order_by(LeadWhatsAppMessage.created_at.desc())
                .limit(CONVERSATION_LIMIT)
            )
        ).all()
    )
    messages.reverse()
    last_inbound = max(
        (m.meta_time or m.created_at for m in messages if m.direction == "in"), default=None
    )
    rows = await numbers(desk.db, desk.tenant_id)
    first = number_config(rows[0])["first_reply"] if rows else None
    opted, how = await opt_in_state(desk.db, lead, first)
    return Conversation(lead, messages, last_inbound, opted, how, rows)


async def record_opt_in(
    desk: LeadDesk, lead_id: UUID, *, command_id: UUID, agreed: bool, how: str
) -> None:
    """The seller records the person's yes (or no) to WhatsApp, with how they said it."""
    seen = await desk._command_seen(command_id)
    if seen is not None:
        return
    lead = await _lead(desk, lead_id)
    desk._event(
        lead,
        "edited",
        {OPT_IN: agreed, "how": how.strip()[:200] or None},
        actor=desk.viewer.person_id,
        command_id=command_id,
    )
    lead.updated_at = desk.now
    await desk.db.flush()


# ----- sending ------------------------------------------------------------------------------


async def approved_templates(
    db: AsyncSession, row: LeadWhatsAppNumber
) -> list[LeadWhatsAppTemplate]:
    return list(
        (
            await db.scalars(
                select(LeadWhatsAppTemplate)
                .where(
                    LeadWhatsAppTemplate.tenant_id == row.tenant_id,
                    LeadWhatsAppTemplate.waba_id == row.waba_id,
                    LeadWhatsAppTemplate.status == "APPROVED",
                )
                .order_by(LeadWhatsAppTemplate.name, LeadWhatsAppTemplate.language)
            )
        ).all()
    )


async def send(
    desk: LeadDesk,
    cfg: cloud.WhatsAppConfig,
    api: cloud.Cloud,
    lead_id: UUID,
    *,
    command_id: UUID,
    number_id: UUID | None,
    body: str | None,
    template: str | None,
    language: str | None,
    values: Sequence[str],
    auto: str | None = None,
) -> LeadWhatsAppMessage:
    """Send one WhatsApp to a lead from one of the organisation's numbers."""
    parts = 0
    seen = await desk.db.scalar(
        select(LeadEvent).where(
            LeadEvent.tenant_id == desk.tenant_id, LeadEvent.command_id == command_id
        )
    )
    if seen is not None:
        existing = await desk.db.scalar(
            select(LeadWhatsAppMessage).where(
                LeadWhatsAppMessage.id == UUID(str((seen.data or {}).get("message_id")))
            )
        )
        if existing is not None:
            return existing
        raise DeskError(409, "That request was already used.")
    lead = await desk._lead(lead_id, lock=True) if auto else await _lead(desk, lead_id)
    wa = cloud.wa_id(lead.phone)
    if wa is None:
        raise DeskError(422, "Add a phone number with its country code to WhatsApp this lead.")
    rows = await numbers(desk.db, desk.tenant_id)
    row = next((r for r in rows if number_id is None or r.id == number_id), None)
    if row is None:
        raise DeskError(409, "Connect a WhatsApp number in Settings → Integrations first.")
    chat = await conversation(desk, lead.id) if not auto else None
    last_inbound = chat.last_inbound if chat else await _last_inbound(desk.db, lead)
    values = [str(value).strip()[:1024] for value in values][:10]
    shown: str | None
    if template is None:
        text_value = (body or "").strip()
        if not text_value:
            raise DeskError(422, "Write a message.")
        if not cloud.window_open(last_inbound, desk.now):
            raise DeskError(
                409,
                "It's more than 24 hours since their last message: send an approved template.",
            )
        shown, kind = text_value[: cloud.TEXT_LIMIT], "text"
    else:
        approved = {(t.name, t.language): t for t in await approved_templates(desk.db, row)}
        chosen = approved.get((template, language or ""))
        if chosen is None:
            raise DeskError(422, "Pick an approved template.")
        parts = needed = cloud.placeholders(cloud.template_text(chosen.components))
        if len([v for v in values if v]) < needed:
            raise DeskError(422, f"Fill in all {needed} parts of the template.")
        if not cloud.window_open(last_inbound, desk.now) and not auto:
            agreed, _ = await opt_in_state(desk.db, lead, number_config(row)["first_reply"])
            if not agreed:
                raise DeskError(
                    409,
                    "They haven't agreed to WhatsApp yet. When they say yes, mark it on the lead.",
                )
        shown, kind = (
            cloud.fill(cloud.template_text(chosen.components), values[:needed]),
            "template",
        )
    message = LeadWhatsAppMessage(
        id=uuid4(),
        tenant_id=desk.tenant_id,
        number_id=row.id,
        lead_id=lead.id,
        wa_id=wa,
        direction="out",
        kind=kind,
        body=shown,
        template_name=template,
        template_language=language if template else None,
        status="queued",
        sent_by_person_id=None if auto else desk.viewer.person_id,
        auto=auto,
        created_at=desk.now,
    )
    desk.db.add(message)
    try:
        if template is None:
            wamid = await api.send_text(
                row.phone_number_id, token(cfg, row), to=wa, body=shown or ""
            )
        else:
            wamid = await api.send_template(
                row.phone_number_id,
                token(cfg, row),
                to=wa,
                name=template,
                language=language or "",
                values=values[:parts],
            )
        message.wamid = wamid
        message.status = "sent"
        message.status_at = desk.now
    except cloud.WhatsAppError as error:
        message.status = "failed"
        message.error_code = str(error.code) if error.code is not None else "refused"
        message.error_title = str(error)[:200]
    desk._event(
        lead,
        "message",
        {
            "channel": "whatsapp",
            "via": "cloud",
            "template": None,
            "whatsapp_template": template,
            "message_id": str(message.id),
            "auto": auto,
            "failed": message.status == "failed",
        },
        actor=None if auto else desk.viewer.person_id,
        command_id=command_id,
    )
    lead.updated_at = desk.now
    await desk.db.flush()
    return message


async def _last_inbound(db: AsyncSession, lead: Lead) -> datetime | None:
    at: datetime | None = await db.scalar(
        select(
            func.max(func.coalesce(LeadWhatsAppMessage.meta_time, LeadWhatsAppMessage.created_at))
        ).where(_chat_filter(lead), LeadWhatsAppMessage.direction == "in")
    )
    return at


# ----- the inbox ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Thread:
    lead_id: UUID | None
    lead_name: str
    wa_id: str
    last_text: str | None
    last_at: datetime
    last_direction: str
    waiting: bool
    window_open: bool


_THREADS = """
    SELECT DISTINCT ON (m.wa_id, m.number_id)
           m.lead_id, m.wa_id, m.body, m.kind, m.direction,
           COALESCE(m.meta_time, m.created_at) AS at
    FROM lead_desk_whatsapp_messages m
    WHERE m.tenant_id = :tenant AND m.erased_at IS NULL AND m.created_at >= :since
    ORDER BY m.wa_id, m.number_id, COALESCE(m.meta_time, m.created_at) DESC, m.id DESC
"""


async def inbox(desk: LeadDesk, *, days: int = 30) -> list[Thread]:
    """Conversations of the last month, newest first; a seller sees their own leads'."""
    rows = (
        await desk.db.execute(
            text(_THREADS), {"tenant": desk.tenant_id, "since": desk.now - timedelta(days=days)}
        )
    ).all()
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
    inbound = {
        row.wa_id: row.at
        for row in (
            await desk.db.execute(
                select(
                    LeadWhatsAppMessage.wa_id,
                    func.max(
                        func.coalesce(LeadWhatsAppMessage.meta_time, LeadWhatsAppMessage.created_at)
                    ).label("at"),
                )
                .where(
                    LeadWhatsAppMessage.tenant_id == desk.tenant_id,
                    LeadWhatsAppMessage.direction == "in",
                )
                .group_by(LeadWhatsAppMessage.wa_id)
            )
        ).all()
    }
    out: list[Thread] = []
    for row in rows:
        lead = leads.get(row.lead_id) if row.lead_id else None
        if not desk.viewer.can_manage and (
            lead is None or lead.owner_person_id != desk.viewer.person_id
        ):
            continue
        out.append(
            Thread(
                lead_id=lead.id if lead else None,
                lead_name=lead.name if lead else cloud.e164(row.wa_id),
                wa_id=row.wa_id,
                last_text=row.body if row.body else None,
                last_at=row.at,
                last_direction=row.direction,
                waiting=row.direction == "in",
                window_open=cloud.window_open(inbound.get(row.wa_id), desk.now),
            )
        )
    out.sort(key=lambda thread: (not thread.waiting, -thread.last_at.timestamp()))
    return out[:INBOX_LIMIT]


# ----- templates ----------------------------------------------------------------------------


async def sync_templates(
    db: AsyncSession,
    cfg: cloud.WhatsAppConfig,
    api: cloud.Cloud,
    row: LeadWhatsAppNumber,
    *,
    now: datetime,
) -> int:
    """Bring the account's templates in from Meta; ones gone at Meta go here too."""
    found = await api.templates(row.waba_id, token(cfg, row))
    keep: set[tuple[str, str]] = set()
    for item in found:
        name, language = str(item.get("name") or ""), str(item.get("language") or "")
        category = str(item.get("category") or "").upper()
        if not name or not language or category not in ("MARKETING", "UTILITY", "AUTHENTICATION"):
            continue
        keep.add((name, language))
        quality = item.get("quality_score")
        values: dict[str, Any] = {
            "meta_id": str(item.get("id") or "")[:32] or None,
            "category": category,
            "status": str(item.get("status") or "")[:24],
            "components": item.get("components")
            if isinstance(item.get("components"), list)
            else [],
            "quality": str(quality.get("score"))[:16]
            if isinstance(quality, Mapping) and quality.get("score")
            else None,
            "rejected_reason": str(item.get("rejected_reason") or "")[:200] or None,
            "synced_at": now,
            "updated_at": now,
            "number_id": row.id,
        }
        await db.execute(
            insert(LeadWhatsAppTemplate)
            .values(
                id=uuid4(),
                tenant_id=row.tenant_id,
                waba_id=row.waba_id,
                name=name[:512],
                language=language[:16],
                created_at=now,
                **values,
            )
            .on_conflict_do_update(
                index_elements=["tenant_id", "waba_id", "name", "language"], set_=values
            )
        )
    stale = [
        template
        for template in (
            await db.scalars(
                select(LeadWhatsAppTemplate).where(
                    LeadWhatsAppTemplate.tenant_id == row.tenant_id,
                    LeadWhatsAppTemplate.waba_id == row.waba_id,
                )
            )
        ).all()
        if (template.name, template.language) not in keep
    ]
    for template in stale:
        await db.delete(template)
    return len(keep)


async def create_template(
    desk: LeadDesk,
    cfg: cloud.WhatsAppConfig,
    api: cloud.Cloud,
    row: LeadWhatsAppNumber,
    *,
    name: str,
    language: str,
    category: str,
    body: str,
    example: list[str],
) -> None:
    """Send a new template to Meta for review; it shows as pending until Meta decides."""
    desk._require_manager()
    if not cloud.TEMPLATE_NAME.fullmatch(name):
        raise DeskError(422, "Use lower-case letters, numbers and underscores for the name.")
    if not cloud.LANGUAGE.fullmatch(language):
        raise DeskError(422, "Pick the template's language.")
    if category not in ("MARKETING", "UTILITY"):
        raise DeskError(422, "Pick Marketing or Utility.")
    text_value = body.strip()
    if not text_value or len(text_value) > 1024:
        raise DeskError(422, "Write the message, up to 1,024 characters.")
    needed = cloud.placeholders(text_value)
    if len([value for value in example if value.strip()]) < needed:
        raise DeskError(422, f"Give an example for each of the {needed} parts in braces.")
    made = await api.create_template(
        row.waba_id,
        token(cfg, row),
        name=name,
        language=language,
        category=category,
        body=text_value,
        example=[value.strip() for value in example[:needed]],
    )
    await desk.db.execute(
        insert(LeadWhatsAppTemplate)
        .values(
            id=uuid4(),
            tenant_id=row.tenant_id,
            number_id=row.id,
            waba_id=row.waba_id,
            meta_id=str(made.get("id") or "")[:32] or None,
            name=name,
            language=language,
            category=category,
            status=str(made.get("status") or "PENDING")[:24],
            components=[{"type": "BODY", "text": text_value}],
            synced_at=desk.now,
            created_at=desk.now,
            updated_at=desk.now,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "waba_id", "name", "language"])
    )


async def delete_template(
    desk: LeadDesk,
    cfg: cloud.WhatsAppConfig,
    api: cloud.Cloud,
    row: LeadWhatsAppNumber,
    *,
    name: str,
) -> None:
    desk._require_manager()
    await api.delete_template(row.waba_id, token(cfg, row), name=name)
    for template in (
        await desk.db.scalars(
            select(LeadWhatsAppTemplate).where(
                LeadWhatsAppTemplate.tenant_id == row.tenant_id,
                LeadWhatsAppTemplate.waba_id == row.waba_id,
                LeadWhatsAppTemplate.name == name,
            )
        )
    ).all():
        await desk.db.delete(template)


# ----- auto replies ---------------------------------------------------------------------------


def first_name(name: str) -> str:
    words = name.strip().split()
    return words[0][:60] if words and not words[0].startswith("+") else "there"


async def first_replies(
    db: AsyncSession, cfg: cloud.WhatsAppConfig, api: cloud.Cloud, *, now: datetime
) -> int:
    """An instant first reply to new ad leads who said yes to WhatsApp on their form."""
    sent = 0
    for row in (
        await db.scalars(select(LeadWhatsAppNumber).where(LeadWhatsAppNumber.status == "active"))
    ).all():
        rule = number_config(row)["first_reply"]
        if not (rule["on"] and rule["template"] and rule["language"] and rule["consent_question"]):
            continue
        leads = (
            await db.scalars(
                select(Lead)
                .where(
                    Lead.tenant_id == row.tenant_id,
                    Lead.created_at >= now - FIRST_REPLY_WITHIN,
                    Lead.source.in_(("meta", "webhook")),
                    Lead.phone.is_not(None),
                    ~select(LeadWhatsAppMessage.id)
                    .where(
                        LeadWhatsAppMessage.lead_id == Lead.id,
                        LeadWhatsAppMessage.direction == "out",
                    )
                    .exists(),
                )
                .order_by(Lead.created_at)
                .limit(50)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for lead in leads:
            if not form_said_yes(lead.payload, rule["consent_question"]):
                continue
            desk = LeadDesk(
                db,
                Viewer(
                    person_id=row.connected_by_person_id,
                    tenant_id=row.tenant_id,
                    role="system",
                    name="WhatsApp",
                ),
                now=now,
            )
            message = await send(
                desk,
                cfg,
                api,
                lead.id,
                command_id=uuid4(),
                number_id=row.id,
                body=None,
                template=rule["template"],
                language=rule["language"],
                values=[first_name(lead.name)],
                auto="first_reply",
            )
            sent += message.status == "sent"
    return sent


async def out_of_hours_replies(
    db: AsyncSession, cfg: cloud.WhatsAppConfig, api: cloud.Cloud, *, now: datetime
) -> int:
    """A reply to messages that arrive outside work hours, at most once in 12 hours."""
    from ac_platform.lead_desk.models import LeadDeskSettings

    sent = 0
    for row in (
        await db.scalars(select(LeadWhatsAppNumber).where(LeadWhatsAppNumber.status == "active"))
    ).all():
        rule = number_config(row)["out_of_hours"]
        if not (rule["on"] and rule["text"]):
            continue
        settings = await db.get(LeadDeskSettings, row.tenant_id)
        hours = work_hours.parse((settings.config if settings else None) or {})
        if hours is None or work_hours.inside(hours, now):
            continue
        waiting = (
            await db.scalars(
                select(LeadWhatsAppMessage)
                .where(
                    LeadWhatsAppMessage.number_id == row.id,
                    LeadWhatsAppMessage.direction == "in",
                    LeadWhatsAppMessage.created_at >= now - timedelta(minutes=30),
                    LeadWhatsAppMessage.lead_id.is_not(None),
                )
                .order_by(LeadWhatsAppMessage.created_at)
                .limit(50)
            )
        ).all()
        done: set[str] = set()
        for message in waiting:
            if message.wa_id in done or message.lead_id is None:
                continue
            done.add(message.wa_id)
            recent = await db.scalar(
                select(func.count())
                .select_from(LeadWhatsAppMessage)
                .where(
                    LeadWhatsAppMessage.number_id == row.id,
                    LeadWhatsAppMessage.wa_id == message.wa_id,
                    LeadWhatsAppMessage.direction == "out",
                    or_(
                        LeadWhatsAppMessage.auto == "out_of_hours",
                        LeadWhatsAppMessage.created_at >= message.created_at,
                    ),
                    LeadWhatsAppMessage.created_at >= now - OUT_OF_HOURS_EVERY,
                )
            )
            if recent:
                continue
            desk = LeadDesk(
                db,
                Viewer(
                    person_id=row.connected_by_person_id,
                    tenant_id=row.tenant_id,
                    role="system",
                    name="WhatsApp",
                ),
                now=now,
            )
            reply = await send(
                desk,
                cfg,
                api,
                message.lead_id,
                command_id=uuid4(),
                number_id=row.id,
                body=rule["text"],
                template=None,
                language=None,
                values=[],
                auto="out_of_hours",
            )
            sent += reply.status == "sent"
    return sent


_GONE = """
    UPDATE lead_desk_whatsapp_messages m SET body = NULL, media = NULL, erased_at = :now
    WHERE m.id IN (
      SELECT x.id FROM lead_desk_whatsapp_messages x
      WHERE x.erased_at IS NULL AND x.lead_id IS NOT NULL
        AND NOT EXISTS (
          SELECT 1 FROM lead_desk_leads l WHERE l.tenant_id = x.tenant_id AND l.id = x.lead_id
        )
      LIMIT 500
    )
"""


async def erasure_sweep(db: AsyncSession, now: datetime) -> int:
    """A lead that leaves Lead Desk takes its WhatsApp words with it."""
    result = await db.execute(text(_GONE), {"now": now})
    return int(getattr(result, "rowcount", 0) or 0)
