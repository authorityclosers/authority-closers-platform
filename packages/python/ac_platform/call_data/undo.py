"""One tap puts back a lead field the call data engine filled (owner, 25 Oct 2026: the
after-call chain fills the lead by itself, "with provenance… one-tap undo").

The field goes back to what it held before the fill, only while it still holds the
filled value: a person's later change always wins. The write goes through the Lead
Desk's own edit (its owner and revision rules apply), its history row points at the
fill it undid, and the fact becomes the person's "rejected", so the same words never
fill it again.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import select

from ac_platform.call_data import facts
from ac_platform.call_data.models import CallObject
from ac_platform.lead_desk.contracts import LeadEdit
from ac_platform.lead_desk.store import UNDO_OF, LeadDesk, Viewer


async def undo_fill(
    database: Any, viewer: Viewer, object_id: UUID, command_id: UUID, now: datetime
) -> UUID:
    """Undo one fill; returns its lead. Raises FactsError or DeskError (the route says
    them); the same command again changes nothing."""
    lead_id = await database.scalar(
        select(CallObject.lead_id).where(
            CallObject.id == object_id, CallObject.tenant_id == viewer.tenant_id
        )
    )
    if lead_id is None:
        raise facts.FactsError(404, "fact_missing")
    desk = LeadDesk(database, viewer, now=now)
    lead = (await desk.detail(lead_id)).lead
    columns = {
        "name": lead.name,
        "company": lead.company,
        "city": lead.city,
        "interest": lead.interest,
    }
    decided = await database.run_sync(
        lambda session: facts.plan_decision(
            session.connection(),
            tenant_id=viewer.tenant_id,
            object_id=object_id,
            person_id=viewer.person_id,
            decision="rejected",
            value=None,
            command_id=command_id,
            now=now,
        )
    )
    if decided.replayed:
        return UUID(str(lead_id))
    undo = await database.run_sync(
        lambda session: facts.plan_undo_fill(
            session.connection(),
            tenant_id=viewer.tenant_id,
            lead_id=lead_id,
            object_id=object_id,
            lead_columns=columns,
        )
    )
    await desk.edit(
        lead_id,
        LeadEdit(
            command_id=uuid5(command_id, "undo-fill"),
            expected_revision=lead.revision,
            **{undo.field: undo.before or ""},
        ),
        marks={"via": "undo_fill", UNDO_OF: str(undo.event_id)},
    )
    await database.run_sync(
        lambda session: facts.save_decision(session.connection(), decided, lead_written=False)
    )
    await database.flush()
    return UUID(str(lead_id))
