"""Read marks: which messages each person has not seen yet, on every device.

A person's mark on a conversation moves forward when they open it in Chats (the page
says up to which message it showed). A message counts as unread for a person when it
came in after their mark and after the team's last reply written by a person: someone
answered it, so it no longer waits to be read. Automatic replies don't count as an
answer. Marks are added, never changed (``LeadChatRead``); the newest one wins.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy import func, select, text

from ac_platform.lead_desk.chats.models import LeadChatRead
from ac_platform.lead_desk.models import LeadSocialMessage, LeadWhatsAppMessage
from ac_platform.lead_desk.store import DeskError, LeadDesk

CHANNELS: Final[tuple[str, ...]] = ("whatsapp", "messenger", "instagram")
# The inboxes show the last month; older messages never count as unread.
WINDOW: Final[timedelta] = timedelta(days=30)

# (channel, account, lead) -> how many of their messages this person hasn't seen.
Unread = dict[tuple[str, UUID, UUID], int]

_WHATSAPP = """
    WITH marks AS (
        SELECT r.account_id, r.lead_id, MAX(r.read_to) AS at
        FROM lead_desk_chat_reads r
        WHERE r.tenant_id = :tenant AND r.person_id = :person AND r.channel = 'whatsapp'
        GROUP BY r.account_id, r.lead_id
    ), answered AS (
        SELECT o.number_id, o.lead_id, MAX(COALESCE(o.meta_time, o.created_at)) AS at
        FROM lead_desk_whatsapp_messages o
        WHERE o.tenant_id = :tenant AND o.direction = 'out' AND o.auto IS NULL
          AND o.lead_id IS NOT NULL AND o.created_at >= :since
        GROUP BY o.number_id, o.lead_id
    )
    SELECT m.number_id AS account_id, m.lead_id, COUNT(*) AS unread
    FROM lead_desk_whatsapp_messages m
    LEFT JOIN marks k ON k.account_id = m.number_id AND k.lead_id = m.lead_id
    LEFT JOIN answered a ON a.number_id = m.number_id AND a.lead_id = m.lead_id
    WHERE m.tenant_id = :tenant AND m.direction = 'in' AND m.kind <> 'reaction'
      AND m.erased_at IS NULL AND m.lead_id IS NOT NULL AND m.created_at >= :since
      AND COALESCE(m.meta_time, m.created_at) > GREATEST(
            COALESCE(k.at, '-infinity'::timestamptz), COALESCE(a.at, '-infinity'::timestamptz))
    GROUP BY m.number_id, m.lead_id
"""

_SOCIAL = """
    WITH marks AS (
        SELECT r.channel, r.account_id, r.lead_id, MAX(r.read_to) AS at
        FROM lead_desk_chat_reads r
        WHERE r.tenant_id = :tenant AND r.person_id = :person
          AND r.channel IN ('messenger', 'instagram')
        GROUP BY r.channel, r.account_id, r.lead_id
    ), answered AS (
        SELECT o.channel, o.account_id, o.lead_id, MAX(COALESCE(o.meta_time, o.created_at)) AS at
        FROM lead_desk_social_messages o
        WHERE o.tenant_id = :tenant AND o.direction = 'out' AND o.auto IS NULL
          AND o.lead_id IS NOT NULL AND o.created_at >= :since
        GROUP BY o.channel, o.account_id, o.lead_id
    )
    SELECT m.channel, m.account_id, m.lead_id, COUNT(*) AS unread
    FROM lead_desk_social_messages m
    LEFT JOIN marks k
      ON k.channel = m.channel AND k.account_id = m.account_id AND k.lead_id = m.lead_id
    LEFT JOIN answered a
      ON a.channel = m.channel AND a.account_id = m.account_id AND a.lead_id = m.lead_id
    WHERE m.tenant_id = :tenant AND m.direction = 'in' AND m.kind <> 'comment'
      AND m.erased_at IS NULL AND m.lead_id IS NOT NULL AND m.created_at >= :since
      AND COALESCE(m.meta_time, m.created_at) > GREATEST(
            COALESCE(k.at, '-infinity'::timestamptz), COALESCE(a.at, '-infinity'::timestamptz))
    GROUP BY m.channel, m.account_id, m.lead_id
"""


async def unread(desk: LeadDesk) -> Unread:
    """Every conversation of the last month with messages this person hasn't seen."""
    params = {
        "tenant": desk.tenant_id,
        "person": desk.viewer.person_id,
        "since": desk.now - WINDOW,
    }
    counts: Unread = {}
    for row in (await desk.db.execute(text(_WHATSAPP), params)).all():
        counts[("whatsapp", row.account_id, row.lead_id)] = int(row.unread)
    for row in (await desk.db.execute(text(_SOCIAL), params)).all():
        counts[(str(row.channel), row.account_id, row.lead_id)] = int(row.unread)
    return counts


async def _newest(desk: LeadDesk, channel: str, account_id: UUID, lead_id: UUID) -> datetime | None:
    """The newest message's time in one conversation, either way."""
    if channel == "whatsapp":
        found: datetime | None = await desk.db.scalar(
            select(
                func.max(
                    func.coalesce(LeadWhatsAppMessage.meta_time, LeadWhatsAppMessage.created_at)
                )
            ).where(
                LeadWhatsAppMessage.tenant_id == desk.tenant_id,
                LeadWhatsAppMessage.number_id == account_id,
                LeadWhatsAppMessage.lead_id == lead_id,
            )
        )
        return found
    found = await desk.db.scalar(
        select(
            func.max(func.coalesce(LeadSocialMessage.meta_time, LeadSocialMessage.created_at))
        ).where(
            LeadSocialMessage.tenant_id == desk.tenant_id,
            LeadSocialMessage.channel == channel,
            LeadSocialMessage.account_id == account_id,
            LeadSocialMessage.lead_id == lead_id,
        )
    )
    return found


async def mark(
    desk: LeadDesk,
    *,
    channel: str,
    lead_id: UUID,
    account_id: UUID,
    read_to: datetime | None,
) -> datetime:
    """This person has seen the conversation up to ``read_to`` (the newest message the
    page showed); never past the newest message there is, nor past now. Returns the
    mark that holds afterwards. Moving backwards changes nothing."""
    if channel not in CHANNELS:
        raise DeskError(422, "Pick WhatsApp, Messenger or Instagram.")
    await desk._lead(lead_id)  # their own leads for a seller; 404 otherwise
    newest = await _newest(desk, channel, account_id, lead_id)
    if newest is None:
        raise DeskError(404, "This chat isn't on your desk.")
    to = min(read_to, newest) if read_to is not None else newest
    to = min(to, desk.now)
    held: datetime | None = await desk.db.scalar(
        select(func.max(LeadChatRead.read_to)).where(
            LeadChatRead.tenant_id == desk.tenant_id,
            LeadChatRead.person_id == desk.viewer.person_id,
            LeadChatRead.channel == channel,
            LeadChatRead.account_id == account_id,
            LeadChatRead.lead_id == lead_id,
        )
    )
    if held is not None and to <= held:
        return held
    desk.db.add(
        LeadChatRead(
            id=uuid4(),
            tenant_id=desk.tenant_id,
            person_id=desk.viewer.person_id,
            channel=channel,
            account_id=account_id,
            lead_id=lead_id,
            read_to=to,
            created_at=desk.now,
        )
    )
    await desk.db.flush()
    return to
