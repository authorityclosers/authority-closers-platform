"""Inbound Leads and Cold Leads (Dipak's final model, the owner's ruling of 30 Oct 2026;
docs/product/lead-desk/stages-views-sources.md §1): which side a lead is on, and each
side's three header numbers. A lead's side is ``lead_desk_leads.pipeline`` (migration
0146): "cold" is Cold; empty or "live" is Inbound. Reads only: nothing here writes."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final, Literal

from pydantic import Field
from sqlalchemy import func, or_, select

from ac_platform.lead_desk.contracts import SCHEMA, Model
from ac_platform.lead_desk.errors import DeskError
from ac_platform.lead_desk.models import Lead
from ac_platform.lead_desk.vocabulary import NEEDS_FOLLOW_UP
from ac_platform.lead_desk.work_views import in_view
from ac_platform.product_updates.reading import lead_lines

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
    enquiries, the To Call list's rows (the badge's number), and the follow-ups booked."""

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
    # The person's unread "<name> is your lead now" lines here, as the bell lists them:
    # Leads waits for this answer before it draws, and raises them with it, so a docked
    # line never pushes the page after it drew (QA robot 10572d93, 2 Nov 2026).
    bell_lines: tuple[dict[str, Any], ...] = ()


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
    # To Call's rows, as the list and the badge count them (#9 option A).
    waiting = await desk._waiting_call_back(team=scope != "mine")
    to_call = in_view("to_call", desk._day_start() + timedelta(days=1), waiting)
    row = (
        await desk.db.execute(
            select(
                func.count().filter(inbound),
                func.count().filter(inbound, Lead.stage == "new"),
                func.count().filter(inbound, to_call),
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
        bell_lines=tuple(await lead_lines(desk.db, desk.viewer.person_id, desk.tenant_id)),
    )
