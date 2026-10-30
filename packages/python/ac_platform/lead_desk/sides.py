"""Inbound Leads and Cold Leads (Dipak's final model, the owner's ruling of 30 Oct 2026;
docs/product/lead-desk/stages-views-sources.md §1): which side a lead is on, and each
side's three header numbers. A lead's side is ``lead_desk_leads.pipeline`` (migration
0146): "cold" is Cold; empty or "live" is Inbound. Reads only: nothing here writes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, Literal

from pydantic import Field
from sqlalchemy import and_, func, or_, select

from ac_platform.lead_desk.contracts import SCHEMA, Model
from ac_platform.lead_desk.errors import DeskError
from ac_platform.lead_desk.models import Lead
from ac_platform.lead_desk.vocabulary import NEEDS_FOLLOW_UP, OPEN_STAGES

if TYPE_CHECKING:
    from ac_platform.lead_desk.store import LeadDesk

Side = Literal["inbound", "cold"]
COLD: Final = "cold"


def on_side(side: Side) -> Any:
    """SQL for the leads on one side; an empty side reads Inbound."""
    if side == "cold":
        return Lead.pipeline == COLD
    return or_(Lead.pipeline.is_(None), Lead.pipeline != COLD)


def is_cold(lead: Lead) -> bool:
    return lead.pipeline == COLD


class InboundNumbers(Model):
    """Every inbound lead (with Cold's Imported: whether someone has both lead types), new
    enquiries, the leads due a call now, and the follow-ups booked."""

    leads: int
    new: int
    to_call: int
    follow_ups: int


class ColdNumbers(Model):
    """Every cold lead, the ones nobody has tried yet, and the ones tried at least once."""

    imported: int
    unworked: int
    attempted: int


class SideNumbers(Model):
    schema_: Literal["lead-desk/1"] = Field(SCHEMA, alias="schema")
    inbound: InboundNumbers
    cold: ColdNumbers


async def side_numbers(desk: LeadDesk, *, scope: Literal["mine", "team"]) -> SideNumbers:
    """Both sides' header numbers for the same people as the list: the seller's own
    leads, or the team's for those who see the team. One read, so switching sides
    shows its numbers at once."""
    if scope != "mine" and not desk.viewer.can_see_team:
        raise DeskError(403, "Your role sees your own leads only.")
    where: list[Any] = [desk._seen()]
    if scope == "mine":
        where.append(Lead.owner_person_id == desk.viewer.person_id)
    inbound, cold = on_side("inbound"), on_side("cold")
    # Due now: a time that has come, or a new lead nobody has called yet.
    due = or_(
        Lead.next_action_at <= desk.now,
        and_(Lead.stage == "new", Lead.next_action_at.is_(None)),
    )
    row = (
        await desk.db.execute(
            select(
                func.count().filter(inbound),
                func.count().filter(inbound, Lead.stage == "new"),
                func.count().filter(inbound, Lead.stage.in_(OPEN_STAGES), due),
                func.count().filter(
                    inbound, Lead.stage.in_(NEEDS_FOLLOW_UP), Lead.next_action_at.is_not(None)
                ),
                func.count().filter(cold),
                func.count().filter(cold, Lead.stage == "new"),
                func.count().filter(cold, Lead.attempts > 0),
            ).where(*where)
        )
    ).one()
    return SideNumbers(
        inbound=InboundNumbers(
            leads=int(row[0]), new=int(row[1]), to_call=int(row[2]), follow_ups=int(row[3])
        ),
        cold=ColdNumbers(imported=int(row[4]), unworked=int(row[5]), attempted=int(row[6])),
    )
