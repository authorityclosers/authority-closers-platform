"""AI replies: drafting for a seller, answering by itself, and handing to a person.

Each reply runs in three steps so no database lock is held while the model thinks:

1. ``prepare`` (in a transaction): the organisation's settings, the lead, this
   channel's last messages, and whether Meta's 24-hour window is open.
2. The rules (``rules.before``) decide without a model: a stop, a hand-off, or go. Only
   then is the model asked (``Model.complete``), through the AI provider registry and
   its budget caps; then ``rules.after`` checks the draft.
3. ``record`` (another transaction): the audit row (``lead_desk_ai_replies``: outcome,
   reason, model, tokens, cost), and in auto mode the send itself, through the
   channel's own send (WhatsApp or Messenger/Instagram, ``auto="ai_reply"``).

A hand-off alerts the lead's seller. A stop marks the person's no on WhatsApp (so no
template goes to them either) and no automatic AI reply goes to them on that channel
again. AI replies never stop the first-response clock: they are automatic.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Protocol
from uuid import UUID, uuid4

from sqlalchemy import exists, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.lead_desk.ai_replies import prompt, rules
from ac_platform.lead_desk.models import (
    Lead,
    LeadAiReply,
    LeadDeskSettings,
    LeadDevice,
    LeadSocialMessage,
    LeadWhatsAppMessage,
)
from ac_platform.lead_desk.social import graph as social_graph
from ac_platform.lead_desk.store import DeskError, LeadDesk, Viewer
from ac_platform.lead_desk.whatsapp import cloud

log = logging.getLogger(__name__)

AUTO_WITHIN: Final[timedelta] = timedelta(minutes=10)
AUTO_BATCH: Final[int] = 20
HANDOFF_LOOK_BACK: Final[timedelta] = timedelta(days=2)


class ModelUnavailable(Exception):
    """No AI provider is set up for Sales Xray, or the budget cap is reached."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason  # "budget" or "failed"


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_inr: Decimal | None
    usage_ref: str | None = None


class Model(Protocol):
    """A text model behind the AI provider registry and its budget caps."""

    async def complete(self, *, tenant_id: UUID, system: str, user: str) -> Completion: ...


# ----- one conversation -----------------------------------------------------------------


@dataclass(slots=True)
class Prepared:
    tenant_id: UUID
    lead_id: UUID
    lead_name: str
    owner_person_id: UUID | None
    payload: Any
    channel: str
    account_id: UUID | None
    settings: rules.Settings
    turns: list[prompt.Turn] = field(default_factory=list)
    last_in_id: UUID | None = None
    last_in_text: str | None = None
    window_open: bool = False


async def _settings(db: AsyncSession, tenant_id: UUID) -> rules.Settings:
    row = await db.get(LeadDeskSettings, tenant_id)
    return rules.read((row.config if row else None) or {})


async def prepare(
    db: AsyncSession,
    lead: Lead,
    channel: str,
    *,
    account_id: UUID | None = None,
    now: datetime,
) -> Prepared:
    """What the reply needs, read in one go."""
    settings = await _settings(db, lead.tenant_id)
    out = Prepared(
        tenant_id=lead.tenant_id,
        lead_id=lead.id,
        lead_name=lead.name,
        owner_person_id=lead.owner_person_id,
        payload=lead.payload,
        channel=channel,
        account_id=account_id,
        settings=settings,
    )
    if channel == "whatsapp":
        wa = cloud.wa_id(lead.phone)
        wa_query = select(LeadWhatsAppMessage).where(
            LeadWhatsAppMessage.tenant_id == lead.tenant_id,
            LeadWhatsAppMessage.erased_at.is_(None),
            (LeadWhatsAppMessage.lead_id == lead.id)
            | (LeadWhatsAppMessage.wa_id == wa if wa else LeadWhatsAppMessage.id.is_(None)),
        )
        rows: Sequence[Any] = (
            await db.scalars(wa_query.order_by(LeadWhatsAppMessage.created_at.desc()).limit(20))
        ).all()
        kinds_ok = {"text", "button", "interactive"}
    else:
        query = select(LeadSocialMessage).where(
            LeadSocialMessage.tenant_id == lead.tenant_id,
            LeadSocialMessage.lead_id == lead.id,
            LeadSocialMessage.channel == channel,
            LeadSocialMessage.erased_at.is_(None),
            LeadSocialMessage.kind != "comment",
        )
        if account_id is not None:
            query = query.where(LeadSocialMessage.account_id == account_id)
        rows = (
            await db.scalars(query.order_by(LeadSocialMessage.created_at.desc()).limit(20))
        ).all()
        kinds_ok = {"text", "postback"}
    ordered = list(reversed(rows))
    for row in ordered:
        if row.body:
            out.turns.append(prompt.Turn(row.direction, row.body))
    last_in = next((row for row in reversed(ordered) if row.direction == "in"), None)
    if last_in is not None:
        at = last_in.meta_time or last_in.created_at
        out.last_in_id = last_in.id
        out.last_in_text = last_in.body if last_in.kind in kinds_ok else None
        out.window_open = (
            cloud.window_open(at, now)
            if channel == "whatsapp"
            else social_graph.window_open(at, now)
        )
        if account_id is None and channel != "whatsapp":
            out.account_id = getattr(last_in, "account_id", None)
    return out


@dataclass(slots=True)
class Outcome:
    outcome: str  # drafted, sent, handoff, opted_out, failed, paused
    reason: str | None = None
    draft: str | None = None
    completion: Completion | None = None
    notes: list[str] = field(default_factory=list)


async def think(model: Model, ready: Prepared) -> Outcome:
    """The rules, then (only if they allow) the model, then the rules on its draft."""
    decided = rules.before(ready.last_in_text, ready.settings, window_open=ready.window_open)
    if decided.stop:
        return Outcome("opted_out", "opt_out")
    if not decided.go:
        return Outcome("handoff", decided.reason)
    system, user = prompt.build(
        ready.settings,
        channel=ready.channel,
        lead_name=ready.lead_name,
        payload=ready.payload,
        turns=ready.turns,
    )
    try:
        completion = await model.complete(tenant_id=ready.tenant_id, system=system, user=user)
    except ModelUnavailable as error:
        return Outcome("paused" if error.reason in ("budget", "off") else "failed", error.reason)
    answer = prompt.read_answer(completion.text)
    checked = rules.after(
        answer.reply, ready.settings, model_handoff=answer.handoff, model_reason=answer.reason
    )
    if not checked.ok:
        return Outcome("handoff", checked.reason, completion=completion, notes=checked.notes)
    return Outcome("drafted", None, draft=checked.reply, completion=completion)


def audit(
    ready: Prepared,
    result: Outcome,
    *,
    mode: str,
    now: datetime,
    by: UUID | None = None,
    sent_message_id: UUID | None = None,
) -> LeadAiReply:
    done = result.completion
    return LeadAiReply(
        id=uuid4(),
        tenant_id=ready.tenant_id,
        lead_id=ready.lead_id,
        channel=ready.channel,
        message_id=ready.last_in_id,
        mode=mode,
        outcome=result.outcome,
        reason=result.reason,
        draft=(result.draft or None) if result.outcome in ("drafted", "sent") else None,
        sent_message_id=sent_message_id,
        provider=done.provider[:64] if done else None,
        model=done.model[:128] if done else None,
        input_tokens=done.input_tokens if done else None,
        output_tokens=done.output_tokens if done else None,
        cost_inr=done.cost_inr if done else None,
        usage_ref=done.usage_ref[:64] if done and done.usage_ref else None,
        requested_by_person_id=by,
        created_at=now,
    )


async def opted_out(db: AsyncSession, lead_id: UUID, channel: str) -> bool:
    return bool(
        await db.scalar(
            select(
                exists().where(
                    LeadAiReply.lead_id == lead_id,
                    LeadAiReply.channel == channel,
                    LeadAiReply.outcome == "opted_out",
                )
            )
        )
    )


async def record_stop(desk: LeadDesk, lead: Lead, channel: str) -> None:
    """They said STOP: on WhatsApp that is their recorded no (templates stop too)."""
    if channel == "whatsapp":
        from ac_platform.lead_desk.whatsapp import inbox as wa_inbox

        desk._event(
            lead,
            "edited",
            {wa_inbox.OPT_IN: False, "how": "They asked to stop (AI replies)"},
            actor=None,
        )


# ----- suggest: a seller asks for a draft -------------------------------------------------


@dataclass(frozen=True, slots=True)
class Draft:
    reply_id: UUID
    draft: str | None
    handoff: bool
    reason: str | None


async def lead_for(desk: LeadDesk, lead_id: UUID) -> Lead:
    lead = await desk.db.get(Lead, lead_id)
    if lead is None or lead.tenant_id != desk.tenant_id:
        raise DeskError(404, "That lead isn't here.")
    if not (desk.viewer.can_manage or lead.owner_person_id == desk.viewer.person_id):
        raise DeskError(403, "Only the lead's owner or a manager can answer them.")
    return lead


# ----- auto: answering by itself -----------------------------------------------------------


_WAITING_WHATSAPP = """
    SELECT m.id, m.lead_id, 'whatsapp' AS channel, NULL::uuid AS account_id
    FROM lead_desk_whatsapp_messages m
    WHERE m.tenant_id = :tenant AND m.direction = 'in' AND m.lead_id IS NOT NULL
      AND m.created_at >= :since AND m.erased_at IS NULL
      AND NOT EXISTS (
        SELECT 1 FROM lead_desk_whatsapp_messages o
        WHERE o.tenant_id = m.tenant_id AND o.wa_id = m.wa_id AND o.direction = 'out'
          AND o.created_at >= m.created_at)
      AND NOT EXISTS (
        SELECT 1 FROM lead_desk_ai_replies r
        WHERE r.channel = 'whatsapp' AND r.message_id = m.id)
    ORDER BY m.created_at
    LIMIT :batch
"""
_WAITING_SOCIAL = """
    SELECT m.id, m.lead_id, m.channel, m.account_id
    FROM lead_desk_social_messages m
    WHERE m.tenant_id = :tenant AND m.direction = 'in' AND m.lead_id IS NOT NULL
      AND m.kind <> 'comment' AND m.created_at >= :since AND m.erased_at IS NULL
      AND NOT EXISTS (
        SELECT 1 FROM lead_desk_social_messages o
        WHERE o.account_id = m.account_id AND o.channel = m.channel
          AND o.user_id = m.user_id AND o.direction = 'out' AND o.created_at >= m.created_at)
      AND NOT EXISTS (
        SELECT 1 FROM lead_desk_ai_replies r
        WHERE r.channel = m.channel AND r.message_id = m.id)
    ORDER BY m.created_at
    LIMIT :batch
"""


@dataclass(frozen=True, slots=True)
class Waiting:
    tenant_id: UUID
    message_id: UUID
    lead_id: UUID
    channel: str
    account_id: UUID | None


async def waiting(db: AsyncSession, *, now: datetime) -> list[Waiting]:
    """Messages from leads of organisations in auto mode that nobody (and no automation)
    has answered yet, newest ten minutes only."""
    out: list[Waiting] = []
    for row in (await db.scalars(select(LeadDeskSettings))).all():
        settings = rules.read(row.config or {})
        if settings.mode != "auto" or not settings.has_profile:
            continue
        params = {"tenant": row.tenant_id, "since": now - AUTO_WITHIN, "batch": AUTO_BATCH}
        for query in (_WAITING_WHATSAPP, _WAITING_SOCIAL):
            for found in (await db.execute(text(query), params)).all():
                if found.channel in settings.channels:
                    out.append(
                        Waiting(
                            row.tenant_id, found.id, found.lead_id, found.channel, found.account_id
                        )
                    )
    return out


def system_desk(db: AsyncSession, lead: Lead, now: datetime) -> LeadDesk:
    person = lead.owner_person_id or uuid4()
    return LeadDesk(
        db,
        Viewer(person_id=person, tenant_id=lead.tenant_id, role="system", name="AI replies"),
        now=now,
    )


async def owner_tokens(db: AsyncSession, lead: Lead) -> list[str]:
    """The phones of the lead's seller, for a hand-off alert."""
    if lead.owner_person_id is None:
        return []
    return list(
        (
            await db.scalars(
                select(LeadDevice.token).where(
                    LeadDevice.tenant_id == lead.tenant_id,
                    LeadDevice.person_id == lead.owner_person_id,
                )
            )
        ).all()
    )


def handoff_alert(lead: Lead) -> dict[str, str]:
    """FCM data: ids only; the app asks Sales Xray for the words."""
    return {
        "type": "lead_desk",
        "kind": "due",
        "reason": "handoff",
        "lead": str(lead.id),
        "tenant": str(lead.tenant_id),
        "alerts": "1",
        "count": "1",
    }


_GONE = """
    UPDATE lead_desk_ai_replies r SET draft = NULL, erased_at = :now
    WHERE r.id IN (
      SELECT x.id FROM lead_desk_ai_replies x
      WHERE x.erased_at IS NULL AND x.draft IS NOT NULL
        AND NOT EXISTS (
          SELECT 1 FROM lead_desk_leads l WHERE l.tenant_id = x.tenant_id AND l.id = x.lead_id
        )
      LIMIT 500
    )
"""


async def erasure_sweep(db: AsyncSession, now: datetime) -> int:
    """A lead that leaves Lead Desk takes the AI's drafts for them with it."""
    result = await db.execute(text(_GONE), {"now": now})
    return int(getattr(result, "rowcount", 0) or 0)


async def recent_handoffs(db: AsyncSession, lead_id: UUID, *, now: datetime) -> list[LeadAiReply]:
    """The last two days' hand-offs on this lead, newest first, one per channel."""
    rows = (
        await db.scalars(
            select(LeadAiReply)
            .where(
                LeadAiReply.lead_id == lead_id,
                LeadAiReply.outcome.in_(("handoff", "opted_out", "paused")),
                LeadAiReply.created_at >= now - HANDOFF_LOOK_BACK,
            )
            .order_by(LeadAiReply.created_at.desc())
            .limit(20)
        )
    ).all()
    seen: set[str] = set()
    out: list[LeadAiReply] = []
    for row in rows:
        if row.channel in seen:
            continue
        seen.add(row.channel)
        if not await _answered_since(db, row):
            out.append(row)
    return out


async def _answered_since(db: AsyncSession, row: LeadAiReply) -> bool:
    """A person has written to the lead on this channel since the hand-off."""
    if row.channel == "whatsapp":
        table: Any = LeadWhatsAppMessage
        extra = []
    else:
        table = LeadSocialMessage
        extra = [LeadSocialMessage.channel == row.channel]
    return bool(
        await db.scalar(
            select(
                exists().where(
                    table.lead_id == row.lead_id,
                    table.direction == "out",
                    table.sent_by_person_id.is_not(None),
                    table.created_at > row.created_at,
                    *extra,
                )
            )
        )
    )
