"""New leads through the duplicate engine as they arrive (owner, 26 Oct 2026, bug reports #12
and #13: Meta leads de-duplicated "granularly", merged when confidence is high and asked
otherwise; design: docs/product/lead-desk/duplicates.md).

After a source files new leads (a Meta Page's webhook, pull, connect or older leads), the
organisation's pairs are found again at once, not at the next six-hourly scan:
- a Certain pair with a lead made just now (the same email or the same source record; the
  same phone is already a repeat at intake) is merged by the desk: the lead with more human
  work is kept and the new one closes as merged into it (``merging.merge``, which an owner or
  admin can undo for 30 days);
- a Probable or Possible pair waits in the review queue for a person, as before.
A merge that can't go ahead (a lead was merged meanwhile) leaves its pair in the queue. While
another scan of the organisation runs, nothing happens here: that scan, or the next, finds the
pairs. The caller's transaction holds the scan's lock until it commits.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID, uuid5

from sqlalchemy import or_, select

from ac_platform.lead_desk import duplicate_scan, merging
from ac_platform.lead_desk.contracts import MergeLeads
from ac_platform.lead_desk.errors import DeskError
from ac_platform.lead_desk.models import LeadDuplicatePair
from ac_platform.lead_desk.store import LeadDesk, Viewer


@dataclass(frozen=True, slots=True)
class Checked:
    """What the engine did with a batch: pairs merged, and pairs left for review."""

    merged: int = 0
    queued: int = 0


async def after_intake(desk: LeadDesk, made: Sequence[UUID]) -> Checked:
    """Find the organisation's pairs again and merge the certain ones with a lead in
    ``made``; the caller commits."""
    if not made or not await duplicate_scan.lock(desk.db, desk.tenant_id):
        return Checked()
    await duplicate_scan.scan(desk.db, desk.tenant_id, desk.now)
    new = set(made)
    pairs = (
        await desk.db.scalars(
            select(LeadDuplicatePair)
            .where(
                LeadDuplicatePair.tenant_id == desk.tenant_id,
                or_(
                    LeadDuplicatePair.first_lead_id.in_(new),
                    LeadDuplicatePair.second_lead_id.in_(new),
                ),
            )
            .order_by(LeadDuplicatePair.score.desc())
        )
    ).all()
    # The desk merges as the organisation's admin would (a merge asks for a manager); its
    # history and audit lines name the person who connected the source.
    manager = LeadDesk(
        desk.db,
        Viewer(
            person_id=desk.viewer.person_id,
            tenant_id=desk.tenant_id,
            role="admin",
            name=desk.viewer.name,
        ),
        now=desk.now,
    )
    merged = queued = 0
    for pair in pairs:
        if pair.band != "certain" or desk.viewer.person_id is None:
            queued += 1
            continue
        command = MergeLeads(
            command_id=uuid5(
                desk.tenant_id, f"intake-merge:{pair.first_lead_id}:{pair.second_lead_id}"
            ),
            lead_ids=(pair.first_lead_id, pair.second_lead_id),
        )
        try:
            async with desk.db.begin_nested():
                await merging.merge(manager, command)
        except DeskError:
            queued += 1
            continue
        merged += 1
    return Checked(merged, queued)
