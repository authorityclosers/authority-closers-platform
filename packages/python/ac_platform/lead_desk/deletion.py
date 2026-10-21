"""Delete chosen leads for good (owner, 21 Oct 2026: "a simple option with confirmation
for the deletion of certain leads, for example test leads").

Only an owner or admin deletes, from Leads, after one confirm; nothing deletes a lead
by itself. Everything happens in the request's one transaction:

- **Removed:** the lead, its history (events), its first-response breaches and the
  Chats read marks for it.
- **Emptied, kept:** rows other parts of the product keep about the lead lose its words
  and request bodies now, as the "lead is gone" sweeps would on their next pass; ids,
  times, results and attempts stay. That covers WhatsApp, Messenger and Instagram
  messages (Meta's ids stop a re-sent webhook adding them again), AI reply drafts (the
  cost rows stay for Admin), and stages told to ad platforms and partner webhooks (a
  send still waiting is dropped as ``lead_gone``). A row a sender holds at this moment
  is left to its sweep, so a delete never waits on a send.
- **Untouched:** calls recorded with the lead and the call facts drawn from them. They
  are the seller's calls, with their own delete.
- **Audit:** one audit event names who deleted which lead ids, with counts; never a
  name, a number or a word. Audit history is never deleted.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.models import AuditEvent
from ac_platform.call_data.models import CallObject
from ac_platform.lead_desk.chats.models import LeadChatRead
from ac_platform.lead_desk.models import (
    Lead,
    LeadAiReply,
    LeadConversion,
    LeadEvent,
    LeadMetaConversion,
    LeadSlaBreach,
    LeadSocialMessage,
    LeadWhatsAppMessage,
)
from ac_platform.partner_events.models import PartnerLeadEvent

MAX_LEADS: Final = 500
AUDIT_ACTION: Final = "lead_desk.leads.deleted"
AUDIT_RESOURCE: Final = "lead_desk.lead_deletion"
GONE: Final = "lead_gone"
_QUIET: Final = {"synchronize_session": False}


@dataclass(frozen=True, slots=True)
class Removal:
    removed: dict[str, int]
    emptied: dict[str, int]
    kept: dict[str, int]


def _count(result: Any) -> int:
    return int(getattr(result, "rowcount", 0) or 0)


def _free(model: Any, tenant_id: UUID, lead_ids: Sequence[UUID], *conditions: Any) -> Any:
    """These leads' rows that no sender holds right now (a held one waits for its sweep)."""
    return model.id.in_(
        select(model.id)
        .where(model.tenant_id == tenant_id, model.lead_id.in_(lead_ids), *conditions)
        .with_for_update(skip_locked=True)
    )


def _dropped(model: Any, waiting: tuple[str, ...]) -> dict[str, Any]:
    """Empty the body; a send still waiting is dropped because the lead is gone."""
    still = model.status.in_(waiting)
    return {
        "payload": None,
        "status": case((still, "dropped"), else_=model.status),
        "last_error_code": case((still, GONE), else_=model.last_error_code),
    }


async def lock(db: AsyncSession, tenant_id: UUID, lead_ids: Sequence[UUID]) -> list[UUID]:
    """The workspace's leads among these ids, locked in id order (two deletes never deadlock)."""
    found = await db.scalars(
        select(Lead.id)
        .where(Lead.tenant_id == tenant_id, Lead.id.in_(lead_ids))
        .order_by(Lead.id)
        .with_for_update()
    )
    return list(found)


async def done_before(db: AsyncSession, tenant_id: UUID, command_id: UUID) -> AuditEvent | None:
    """The audit event of this command, when it already ran (a retry, a second tap)."""
    event: AuditEvent | None = await db.scalar(
        select(AuditEvent).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.resource_type == AUDIT_RESOURCE,
            AuditEvent.resource_id == str(command_id),
        )
    )
    return event


async def remove(
    db: AsyncSession, tenant_id: UUID, lead_ids: Sequence[UUID], now: datetime
) -> Removal:
    """Remove locked leads and their own rows; empty what others keep about them."""
    ids = list(lead_ids)

    def mine(model: Any) -> tuple[Any, ...]:
        return (model.tenant_id == tenant_id, model.lead_id.in_(ids))

    submission = LeadEvent.data["submission_id"].as_string()
    kept = {
        "call_facts": int(
            await db.scalar(select(func.count()).select_from(CallObject).where(*mine(CallObject)))
            or 0
        ),
        "recorded_calls": int(
            await db.scalar(
                select(func.count(func.distinct(submission))).where(
                    *mine(LeadEvent), LeadEvent.kind == "call", submission.is_not(None)
                )
            )
            or 0
        ),
    }

    emptied = {
        "whatsapp_messages": _count(
            await db.execute(
                update(LeadWhatsAppMessage)
                .where(
                    _free(
                        LeadWhatsAppMessage,
                        tenant_id,
                        ids,
                        LeadWhatsAppMessage.erased_at.is_(None),
                    )
                )
                .values(body=None, media=None, erased_at=now)
                .execution_options(**_QUIET)
            )
        ),
        "social_messages": _count(
            await db.execute(
                update(LeadSocialMessage)
                .where(
                    _free(LeadSocialMessage, tenant_id, ids, LeadSocialMessage.erased_at.is_(None))
                )
                .values(body=None, user_name=None, erased_at=now)
                .execution_options(**_QUIET)
            )
        ),
        "ai_replies": _count(
            await db.execute(
                update(LeadAiReply)
                .where(
                    _free(
                        LeadAiReply,
                        tenant_id,
                        ids,
                        LeadAiReply.erased_at.is_(None),
                        LeadAiReply.draft.is_not(None),
                        LeadAiReply.mode != "try",
                    )
                )
                .values(draft=None, erased_at=now)
                .execution_options(**_QUIET)
            )
        ),
        "stage_events": _count(
            await db.execute(
                update(LeadConversion)
                .where(_free(LeadConversion, tenant_id, ids, LeadConversion.payload.is_not(None)))
                .values(erased_at=now, **_dropped(LeadConversion, ("pending",)))
                .execution_options(**_QUIET)
            )
        ),
        "meta_stage_events": _count(
            await db.execute(
                update(LeadMetaConversion)
                .where(
                    _free(
                        LeadMetaConversion, tenant_id, ids, LeadMetaConversion.payload.is_not(None)
                    )
                )
                .values(erased_at=now, **_dropped(LeadMetaConversion, ("pending",)))
                .execution_options(**_QUIET)
            )
        ),
        # A partner send is leased while it runs; a running one finishes, then its sweep.
        "partner_events": _count(
            await db.execute(
                update(PartnerLeadEvent)
                .where(
                    _free(
                        PartnerLeadEvent,
                        tenant_id,
                        ids,
                        PartnerLeadEvent.payload.is_not(None),
                        (PartnerLeadEvent.leased_until.is_(None))
                        | (PartnerLeadEvent.leased_until <= now),
                    )
                )
                .values(
                    erased_at=now,
                    leased_until=None,
                    **_dropped(PartnerLeadEvent, ("pending", "dead_letter")),
                )
                .execution_options(**_QUIET)
            )
        ),
    }

    removed = {
        "events": _count(
            await db.execute(delete(LeadEvent).where(*mine(LeadEvent)).execution_options(**_QUIET))
        ),
        "sla_breaches": _count(
            await db.execute(
                delete(LeadSlaBreach).where(*mine(LeadSlaBreach)).execution_options(**_QUIET)
            )
        ),
        "chat_reads": _count(
            await db.execute(
                delete(LeadChatRead).where(*mine(LeadChatRead)).execution_options(**_QUIET)
            )
        ),
        "leads": _count(
            await db.execute(
                delete(Lead)
                .where(Lead.tenant_id == tenant_id, Lead.id.in_(ids))
                .execution_options(**_QUIET)
            )
        ),
    }
    return Removal(removed=removed, emptied=emptied, kept=kept)
